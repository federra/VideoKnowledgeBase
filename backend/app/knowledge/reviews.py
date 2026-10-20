"""Append-only decisions and current-head publication, in caller-owned transactions."""

from uuid import UUID

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import compare_and_swap
from app.intelligence.service import row
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt

TARGETS = {
    "knowledge_release": ("knowledge_revisions", "knowledge_revision_id", "knowledge.review"),
    "report_review": ("analysis_reports", "report_id", "report.review"),
    "evaluation_review": ("quality_evaluations", "evaluation_id", "evaluation.review"),
    "standard_approval": ("standard_revisions", "standard_revision_id", "standard.approve"),
}


def target(c, p, purpose, ident, action=None):
    az = Authorizer(c, p)
    refresh(c, p)
    kind = TARGETS[purpose][0]
    if kind == "knowledge_revisions":
        return (
            az.require(kind, ident, action, candidate=True) if action else az.candidate(kind, ident)
        )
    return az.require(kind, ident, action) if action else az.read(kind, ident)


def ensure_request(c, p, purpose, ident):
    v = target(c, p, purpose, ident)
    col = TARGETS[purpose][1]
    old = c.exec_driver_sql(
        f"SELECT id FROM review_requests WHERE org_id=%s AND {col}=%s", (p.org_id, ident)
    ).scalar_one_or_none()
    return old or insert(
        c,
        "review_requests",
        p.org_id,
        purpose=purpose,
        **{col: ident},
        input_sha256=v["content_sha256"],
        requested_by=p.member_id,
    )


def access(c, p, ident, action=None):
    r = row(c, "review_requests", p.org_id, ident)
    v = target(c, p, r["purpose"], r[TARGETS[r["purpose"]][1]], action)
    if r["input_sha256"] != v["content_sha256"]:
        raise Denied("REVIEW_STALE")
    return r, v


def heads(c, p, ident):
    values = (
        c.exec_driver_sql(
            "SELECT * FROM review_heads WHERE org_id=%s AND request_id=%s ORDER BY reviewer_kind FOR UPDATE",
            (p.org_id, ident),
        )
        .mappings()
        .all()
    )
    return {h["reviewer_kind"]: dict(h) for h in values}


def pending_review_state(c, p, ident):
    latest = (
        c.exec_driver_sql(
            "SELECT t.* FROM tasks t JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id WHERE t.org_id=%s AND i.review_request_id=%s AND t.kind='knowledge.review' ORDER BY t.created_at DESC,t.id DESC LIMIT 1",
            (p.org_id, ident),
        )
        .mappings()
        .one_or_none()
    )
    if not latest:
        return None
    head = c.exec_driver_sql(
        "SELECT e.task_id FROM review_heads h JOIN review_decisions d ON d.org_id=h.org_id AND d.id=h.decision_id JOIN ai_executions e ON e.org_id=d.org_id AND e.id=d.ai_execution_id WHERE h.org_id=%s AND h.request_id=%s AND h.reviewer_kind='ai'",
        (p.org_id, ident),
    ).scalar_one_or_none()
    if latest["id"] == head and latest["state"] == "succeeded":
        return None
    if latest["state"] == "failed":
        return "ai_error"
    if latest["state"] in ("cancelled", "succeeded"):
        return "needs_changes"
    return "pending_ai"


def immutable(c, p, r, v):
    if r["purpose"] == "knowledge_release":
        if c.exec_driver_sql(
            "SELECT 1 FROM knowledge_publications WHERE org_id=%s AND revision_id=%s",
            (p.org_id, v["id"]),
        ).first():
            raise Denied("REVIEW_STALE")
        k = row(c, "knowledge_items", p.org_id, v["knowledge_id"])
        if k["current_revision_id"] != v["id"]:
            raise Denied("REVIEW_STALE")
    if r["purpose"] == "standard_approval":
        s = row(c, "standards", p.org_id, v["standard_id"])
        if s["active_revision_id"] == v["id"]:
            raise Denied("REVIEW_STALE")


def request_review(c, p, key, request):
    lock_org(c, p.org_id)
    submit = {
        "knowledge_release": "knowledge.edit",
        "report_review": "report.review.run",
        "evaluation_review": "evaluation.review",
        "standard_approval": "standard.approve",
    }[request.purpose]
    if not request.execute_ai:
        target(c, p, request.purpose, request.target_id, submit)
    if request.execute_ai:
        if request.max_external_calls != 1 or request.purpose not in (
            "knowledge_release",
            "report_review",
        ):
            raise Denied("VALIDATION_FAILED")
        target(
            c,
            p,
            request.purpose,
            request.target_id,
            "knowledge.review.run"
            if request.purpose == "knowledge_release"
            else "report.review.run",
        )
    elif request.max_external_calls:
        raise Denied("VALIDATION_FAILED")

    def perform():
        ident = ensure_request(c, p, request.purpose, request.target_id)
        r, v = access(c, p, ident)
        immutable(c, p, r, v)
        if request.execute_ai:
            from app.knowledge.tasks import start_review

            start_review(c, p, key, r, v)
        audit(c, p.org_id, p.member_id, "review.requested", "review_request", ident)
        return {"id": str(ident)}

    saved = receipt(c, p, "requestReview", key, request.model_dump(mode="json"), perform)
    return read_review(c, p, UUID(saved["id"]))


def read_review(c, p, ident):
    lock_org(c, p.org_id)
    r, v = access(c, p, ident)
    hh = heads(c, p, ident)
    decisions = list(
        c.exec_driver_sql(
            "SELECT * FROM review_decisions WHERE org_id=%s AND request_id=%s ORDER BY created_at,id",
            (p.org_id, ident),
        ).mappings()
    )
    task = (
        c.exec_driver_sql(
            "SELECT t.id,t.state FROM tasks t JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id WHERE t.org_id=%s AND i.review_request_id=%s AND t.kind='knowledge.review' ORDER BY t.created_at DESC,t.id DESC LIMIT 1",
            (p.org_id, ident),
        )
        .mappings()
        .one_or_none()
    )
    from app.contracts.models import ReviewDecision
    from app.research.analysis import project

    decisions = [project(ReviewDecision, d).model_dump() for d in decisions]
    return {
        **r,
        "target_id": v["id"],
        "ai_head_id": hh.get("ai", {}).get("decision_id"),
        "human_head_id": hh.get("human", {}).get("decision_id"),
        "ai_head_lock_version": str(hh["ai"]["lock_version"]) if "ai" in hh else None,
        "human_head_lock_version": str(hh["human"]["lock_version"]) if "human" in hh else None,
        "task": {"id": str(task["id"]), "kind": "task", "state": task["state"]} if task else None,
        "decisions": decisions,
    }


def append_decision(
    c,
    p,
    r,
    kind,
    verdict,
    reason,
    *,
    expected_id=None,
    expected_version=None,
    reviewed_ai=None,
    execution=None,
):
    _, v = access(c, p, r["id"])
    immutable(c, p, r, v)
    hh = heads(c, p, r["id"])
    old = hh.get(kind)
    if (old["decision_id"] if old else None) != expected_id or (
        old["lock_version"] if old else None
    ) != (int(expected_version) if expected_version is not None else None):
        raise Denied("REVIEW_STALE")
    if kind == "human" and r["purpose"] in ("knowledge_release", "report_review"):
        ai = hh.get("ai")
        if reviewed_ai != (ai["decision_id"] if ai else None):
            raise Denied("REVIEW_STALE")
        if verdict == "approved" and (
            pending_review_state(c, p, r["id"]) is not None
            or not ai
            or row(c, "review_decisions", p.org_id, ai["decision_id"])["verdict"] != "approved"
        ):
            raise Denied("REVIEW_STALE")
    elif reviewed_ai is not None:
        raise Denied("VALIDATION_FAILED")
    did = insert(
        c,
        "review_decisions",
        p.org_id,
        request_id=r["id"],
        reviewer_kind=kind,
        reviewer_member_id=p.member_id if kind == "human" else None,
        ai_execution_id=execution,
        verdict=verdict,
        reason=reason,
        input_sha256=r["input_sha256"],
        supersedes_decision_id=old["decision_id"] if old else None,
        reviewed_ai_decision_id=reviewed_ai,
    )
    if old:
        c.exec_driver_sql(
            "UPDATE review_heads SET decision_id=%s,lock_version=lock_version+1,updated_at=clock_timestamp() WHERE org_id=%s AND request_id=%s AND reviewer_kind=%s AND lock_version=%s",
            (did, p.org_id, r["id"], kind, old["lock_version"]),
        )
    else:
        c.execute(
            metadata.tables["review_heads"]
            .insert()
            .values(org_id=p.org_id, request_id=r["id"], reviewer_kind=kind, decision_id=did)
        )
    return did


def human_decision(c, p, key, ident, request):
    lock_org(c, p.org_id)
    r, _ = access(c, p, ident, TARGETS[row(c, "review_requests", p.org_id, ident)["purpose"]][2])

    def perform():
        did = append_decision(
            c,
            p,
            r,
            "human",
            request.verdict,
            request.reason,
            expected_id=request.expected_head_id,
            expected_version=request.expected_head_lock_version,
            reviewed_ai=request.reviewed_ai_decision_id,
        )
        audit(c, p.org_id, p.member_id, "review.human_decided", "review_request", ident)
        return {"id": str(did)}

    saved = receipt(
        c,
        p,
        "submitHumanDecision",
        key,
        {"request_id": str(ident), **request.model_dump(mode="json")},
        perform,
    )
    return row(c, "review_decisions", p.org_id, UUID(saved["id"]))


def publish(c, p, key, kid, request):
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    k = az.require("knowledge_items", kid, "knowledge.publish", candidate=True)
    target(c, p, "knowledge_release", request.revision_id, "knowledge.publish")

    def perform():
        r, v = access(c, p, request.review_request_id)
        if pending_review_state(c, p, r["id"]) is not None:
            raise Denied("REVIEW_STALE")
        hh = heads(c, p, r["id"])
        if (
            r["purpose"] != "knowledge_release"
            or v["knowledge_id"] != kid
            or v["id"] != request.revision_id
            or k["current_revision_id"] != v["id"]
        ):
            raise Denied("REVIEW_STALE")
        if (
            hh.get("ai", {}).get("decision_id") != request.ai_decision_id
            or hh.get("human", {}).get("decision_id") != request.human_decision_id
        ):
            raise Denied("REVIEW_STALE")
        a = row(c, "review_decisions", p.org_id, request.ai_decision_id)
        h = row(c, "review_decisions", p.org_id, request.human_decision_id)
        if (
            a["verdict"] != "approved"
            or h["verdict"] != "approved"
            or h["reviewed_ai_decision_id"] != a["id"]
            or a["input_sha256"] != v["content_sha256"]
            or h["input_sha256"] != v["content_sha256"]
        ):
            raise Denied("REVIEW_STALE")
        existing = c.exec_driver_sql(
            "SELECT id FROM knowledge_publications WHERE org_id=%s AND revision_id=%s",
            (p.org_id, v["id"]),
        ).scalar_one_or_none()
        if existing:
            return {"id": str(existing)}
        pub = insert(
            c,
            "knowledge_publications",
            p.org_id,
            knowledge_id=kid,
            revision_id=v["id"],
            review_request_id=r["id"],
            ai_decision_id=a["id"],
            human_decision_id=h["id"],
            published_by=p.member_id,
        )
        compare_and_swap(
            c,
            "knowledge_items",
            p.org_id,
            kid,
            int(request.expected_lock_version),
            {"published_publication_id": pub},
        )
        from app.knowledge.search import index_publication

        index_publication(c, p, pub)
        audit(c, p.org_id, p.member_id, "knowledge.published", "knowledge", kid)
        return {"id": str(pub)}

    saved = receipt(
        c,
        p,
        "publishKnowledge",
        key,
        {"knowledge_id": str(kid), **request.model_dump(mode="json")},
        perform,
    )
    result = row(c, "knowledge_publications", p.org_id, UUID(saved["id"]))
    az.read("knowledge_revisions", result["revision_id"])
    return result


def approve_publish(c, p, key, ident, request):
    from app.contracts.models import HumanDecisionCreate, PublishCreate

    lock_org(c, p.org_id)
    r, v = access(c, p, ident, "knowledge.review")
    if r["purpose"] != "knowledge_release":
        raise Denied("VALIDATION_FAILED")
    Authorizer(c, p).require("knowledge_revisions", v["id"], "knowledge.publish", candidate=True)
    # One transaction: a failed publication rolls back the new human decision too.
    h = human_decision(
        c,
        p,
        key,
        ident,
        HumanDecisionCreate(
            expected_head_id=request.expected_head_id,
            expected_head_lock_version=request.expected_head_lock_version,
            reviewed_ai_decision_id=request.reviewed_ai_decision_id,
            verdict="approved",
            reason=request.reason,
        ),
    )
    return publish(
        c,
        p,
        key,
        v["knowledge_id"],
        PublishCreate(
            expected_lock_version=request.expected_lock_version,
            revision_id=v["id"],
            review_request_id=r["id"],
            ai_decision_id=request.reviewed_ai_decision_id,
            human_decision_id=h["id"],
        ),
    )
