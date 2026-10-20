"""Exact revision services; formal reads never substitute the current candidate."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import compare_and_swap
from app.knowledge.search import normalize
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt


def revision_request(c, p, rid):
    return c.exec_driver_sql(
        "SELECT id FROM review_requests WHERE org_id=%s AND knowledge_revision_id=%s",
        (p.org_id, rid),
    ).scalar_one_or_none()


def state(c, p, rid):
    if c.exec_driver_sql(
        "SELECT 1 FROM knowledge_publications WHERE org_id=%s AND revision_id=%s", (p.org_id, rid)
    ).first():
        return "published"
    req = revision_request(c, p, rid)
    if not req:
        return "draft"
    from app.knowledge.reviews import pending_review_state

    pending = pending_review_state(c, p, req)
    if pending:
        return pending
    heads = (
        c.exec_driver_sql(
            "SELECT h.reviewer_kind,d.* FROM review_heads h JOIN review_decisions d ON d.org_id=h.org_id AND d.id=h.decision_id WHERE h.org_id=%s AND h.request_id=%s",
            (p.org_id, req),
        )
        .mappings()
        .all()
    )
    a = next((d for d in heads if d["reviewer_kind"] == "ai"), None)
    h = next((d for d in heads if d["reviewer_kind"] == "human"), None)
    if not a:
        failed = c.exec_driver_sql(
            "SELECT 1 FROM tasks t JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id WHERE t.org_id=%s AND i.review_request_id=%s AND t.state='failed'",
            (p.org_id, req),
        ).first()
        return "ai_error" if failed else "pending_ai"
    if a["verdict"] == "error":
        return "ai_error"
    if a["verdict"] != "approved":
        return "needs_changes"
    if h and h["reviewed_ai_decision_id"] == a["id"]:
        return "ready_to_publish" if h["verdict"] == "approved" else "needs_changes"
    return "pending_human"


def read_candidate(c, p, rid):
    v = Authorizer(c, p).candidate("knowledge_revisions", rid)
    codes = (
        c.exec_driver_sql(
            "SELECT business_code FROM knowledge_businesses WHERE org_id=%s AND revision_id=%s ORDER BY business_code",
            (p.org_id, rid),
        )
        .scalars()
        .all()
    )
    refs = (
        c.exec_driver_sql(
            "SELECT DISTINCT evidence_id FROM knowledge_evidence WHERE org_id=%s AND revision_id=%s ORDER BY evidence_id",
            (p.org_id, rid),
        )
        .scalars()
        .all()
    )
    from app.contracts.models import KnowledgeRevision
    from app.research.analysis import project

    return project(
        KnowledgeRevision, {**v, "business_codes": list(codes), "evidence_ids": list(refs)}
    ).model_dump()


def detail(c, p, kid, *, candidate=False):
    az = Authorizer(c, p)
    identity = (
        az.candidate("knowledge_items", kid) if candidate else az.read("knowledge_items", kid)
    )
    rid = identity["current_revision_id"]
    if candidate:
        v = read_candidate(c, p, rid)
    else:
        v = az.read("knowledge_revisions", rid)
        v = {
            **v,
            "business_codes": list(
                c.exec_driver_sql(
                    "SELECT business_code FROM knowledge_businesses WHERE org_id=%s AND revision_id=%s ORDER BY business_code",
                    (p.org_id, rid),
                ).scalars()
            ),
            "evidence_ids": list(
                c.exec_driver_sql(
                    "SELECT DISTINCT evidence_id FROM knowledge_evidence WHERE org_id=%s AND revision_id=%s ORDER BY evidence_id",
                    (p.org_id, rid),
                ).scalars()
            ),
        }
    from app.contracts.models import KnowledgeRevision
    from app.research.analysis import project

    v = project(KnowledgeRevision, v).model_dump()
    return {
        **identity,
        "lock_version": str(identity["lock_version"]),
        "revision_id": rid,
        "publication_id": identity["published_publication_id"]
        if not candidate or state(c, p, rid) == "published"
        else None,
        "browse_category": v["browse_category"],
        "business_codes": v["business_codes"],
        "tags": v["tags"],
        "state": state(c, p, rid),
        "revision": v,
        "review_request_id": revision_request(c, p, rid),
    }


def published(c, p, kid):
    return detail(c, p, kid)


def validate(c, p, request):
    az = Authorizer(c, p)
    refresh(c, p)
    if len(set(request.business_codes)) != len(request.business_codes) or len(
        set(request.evidence_ids)
    ) != len(request.evidence_ids):
        raise Denied("VALIDATION_FAILED")
    if not all(
        az.allowed("knowledge.edit", {("org", str(p.org_id)), ("business", b)})
        for b in request.business_codes
    ):
        raise Denied("ACCESS_DENIED")
    source = getattr(request, "manual_source", None)
    if source and (
        request.source_report_id or not az.allowed("evidence.read", {("org", str(p.org_id))})
    ):
        raise Denied("ACCESS_DENIED")
    for eid in request.evidence_ids:
        az.read("evidence_refs", eid)
    if request.source_report_id:
        report = az.read("analysis_reports", request.source_report_id)
        if (
            az.read("works", report["work_id"])["business_code"] not in request.business_codes
            or not request.evidence_ids
        ):
            raise Denied("VALIDATION_FAILED")
        refs = set(
            c.exec_driver_sql(
                "SELECT evidence_id FROM report_evidence WHERE org_id=%s AND report_id=%s",
                (p.org_id, report["id"]),
            ).scalars()
        )
        if not set(request.evidence_ids) <= refs:
            raise Denied("VALIDATION_FAILED")
    return az


def add_revision(c, p, kid, request, version):
    source = getattr(request, "manual_source", None)
    refs = list(request.evidence_ids)
    own_manual = set(
        c.exec_driver_sql(
            "SELECT e.evidence_id FROM knowledge_evidence e JOIN knowledge_revisions r ON r.org_id=e.org_id AND r.id=e.revision_id WHERE r.org_id=%s AND r.knowledge_id=%s AND e.claim_path='manual_source'",
            (p.org_id, kid),
        ).scalars()
    )
    # Explicitly replacing the source drops this knowledge's old submitted source,
    # while preserving separately attached evidence and immutable old revisions.
    managed = set(refs) & own_manual
    if source:
        refs = [e for e in refs if e not in own_manual]
        text = source.body_text + "\n\n【人工提供出处，未独立核验】\n" + source.attribution
        raw = insert(
            c,
            "raw_assets",
            p.org_id,
            origin="manual",
            asset_kind="text",
            submitted_by=p.member_id,
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        eid = insert(
            c,
            "evidence_refs",
            p.org_id,
            raw_asset_id=raw,
            locator_kind="whole",
            quoted_text=source.body_text,
        )
        refs.append(eid)
        managed = {eid}
    values = request.model_dump(mode="json", exclude={"expected_lock_version", "revision_reason"})
    rid = insert(
        c,
        "knowledge_revisions",
        p.org_id,
        knowledge_id=kid,
        version_no=version,
        title=request.title,
        body_text=request.body_text,
        knowledge_type=request.knowledge_type,
        browse_category=request.browse_category,
        tags=values["tags"],
        limitations=request.limitations,
        origin="analysis" if request.source_report_id else "manual",
        source_report_id=request.source_report_id,
        created_by=p.member_id,
        content_sha256=digest(values),
    )
    for b in request.business_codes:
        c.execute(
            metadata.tables["knowledge_businesses"]
            .insert()
            .values(org_id=p.org_id, revision_id=rid, business_code=b)
        )
    for eid in refs:
        c.execute(
            metadata.tables["knowledge_evidence"]
            .insert()
            .values(
                org_id=p.org_id,
                revision_id=rid,
                evidence_id=eid,
                claim_path="manual_source" if eid in managed else "body",
            )
        )
    c.exec_driver_sql("SELECT cip_seal('knowledge_revisions',%s,%s)", (p.org_id, rid))
    from app.knowledge.reviews import ensure_request

    ensure_request(c, p, "knowledge_release", rid)
    return rid


def create(c, p, key, request):
    lock_org(c, p.org_id)
    validate(c, p, request)

    def perform():
        kid = insert(
            c,
            "knowledge_items",
            p.org_id,
            title=request.title,
            owner_member_id=p.member_id,
            created_by=p.member_id,
        )
        rid = add_revision(c, p, kid, request, 1)
        compare_and_swap(c, "knowledge_items", p.org_id, kid, 1, {"current_revision_id": rid})
        audit(c, p.org_id, p.member_id, "knowledge.created", "knowledge", kid)
        return {"id": str(kid)}

    saved = receipt(c, p, "createKnowledge", key, request.model_dump(mode="json"), perform)
    return detail(c, p, UUID(saved["id"]), candidate=True)


def revise(c, p, key, kid, request):
    lock_org(c, p.org_id)
    az = validate(c, p, request)
    identity = az.require("knowledge_items", kid, "knowledge.edit", candidate=True)

    def perform():
        old = az.candidate("knowledge_revisions", identity["current_revision_id"])
        rid = add_revision(c, p, kid, request, old["version_no"] + 1)
        compare_and_swap(
            c,
            "knowledge_items",
            p.org_id,
            kid,
            int(request.expected_lock_version),
            {"current_revision_id": rid, "title": request.title},
        )
        insert(
            c,
            "audit_events",
            p.org_id,
            actor_member_id=p.member_id,
            action_code="knowledge.revised",
            target_kind="knowledge",
            target_id=kid,
            request_id=str(key),
            safe_details={"reason": request.revision_reason, "revision_id": str(rid)},
        )
        return {"id": str(rid)}

    saved = receipt(
        c,
        p,
        "reviseKnowledge",
        key,
        {"knowledge_id": str(kid), **request.model_dump(mode="json")},
        perform,
    )
    return read_candidate(c, p, UUID(saved["id"]))


def listing(c, p, business, *, candidate=False, q=None, category=None, source_report_id=None):
    refresh(c, p)
    items = []
    ids = (
        c.exec_driver_sql(
            "SELECT id FROM knowledge_items WHERE org_id=%s ORDER BY created_at DESC,id DESC",
            (p.org_id,),
        )
        .scalars()
        .all()
    )
    for kid in ids:
        try:
            x = detail(c, p, kid, candidate=candidate)
        except Denied as exc:
            if exc.code == "NOT_FOUND":
                continue
            raise
        v = x["revision"]
        if candidate and x["state"] == "published":
            continue
        if (
            business not in x["business_codes"]
            or (category and x["browse_category"] != category)
            or (source_report_id and v["source_report_id"] != source_report_id)
        ):
            continue
        if q and normalize(q) not in normalize(
            x["title"] + " " + v["body_text"] + " " + (v["limitations"] or "") + " " + str(kid)
        ):
            continue
        items.append(x)
    return {"items": items, "next_cursor": None, "total": str(len(items))}
