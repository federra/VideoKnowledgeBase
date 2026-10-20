"""Immutable single-batch insight projection. Zero external/model calls."""

from uuid import uuid4

from app.collection.service import insert
from app.core.repository import create_task
from app.intelligence.feedback import read_feedback
from app.intelligence.service import row
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import MemberPrincipal, refresh
from app.security.storage import lock_org
from app.tasks.service import TaskError, input_digest


def derive(feedbacks):
    comments = {str(x["id"]) for f in feedbacks for x in f["comments"]}
    classified = set()
    emotions = {}
    suggestions = []
    claim_ids = []
    for full in feedbacks:
        for claim in full["claims"]:
            if claim["kind"] == "emotion":
                ids = {str(x) for x in claim["comment_ids"]}
                classified |= ids
                emotions.setdefault(claim["text"], set()).update(ids)
                claim_ids.append(str(claim["id"]))
            elif claim["kind"] == "suggestion":
                suggestions.append(claim["details"].get("change") or claim["text"])
                claim_ids.append(str(claim["id"]))
    return {
        "sample_count": len(comments),
        "classified_count": len(classified),
        "motif": None,
        "genre": None,
        "emotions": [
            {
                "name": name,
                "count": len(ids),
                "percent": int(len(ids) / len(classified) * 100 + 0.5),
            }
            for name, ids in sorted(emotions.items(), key=lambda x: -len(x[1]))
        ],
        "suggestions": suggestions,
        "source_claim_ids": claim_ids,
        "coverage_note": "仅本批一条作品的首屏评论样本观察；不代表市场整体。母题与题材证据不足，建议方向待验证。",
    }


class InsightTask:
    action = "collection.run"

    def freeze(self, c, task, az, *, feedback_id=None):
        if feedback_id is None:
            ids = (
                c.exec_driver_sql(
                    "SELECT feedback_id FROM task_inputs WHERE org_id=%s AND task_id=%s",
                    (task["org_id"], task["id"]),
                )
                .scalars()
                .all()
            )
            if len(ids) != 1 or ids[0] is None:
                raise TaskError("INVALID_INPUT")
            feedback_id = ids[0]
        full = read_feedback(c, az.p, feedback_id)
        parent = row(c, "feedback_snapshots", task["org_id"], feedback_id)
        parent_task = row(c, "tasks", task["org_id"], parent["task_id"])
        snap = row(c, "intelligence_snapshots", task["org_id"], parent["snapshot_id"])
        az.require("sources", parent_task["source_id"], self.action)
        if (
            task["max_external_calls"] != 0
            or task["source_id"] != parent_task["source_id"]
            or task["business_code"] != snap["business_code"]
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "feedback_id": str(feedback_id),
            "feedback_version": full["version_no"],
            "body": derive([full]),
        }

    def execute(self, payload, checkpoint):
        checkpoint()
        return payload

    def publish(self, c, task, result):
        expected = self.freeze(
            c, task, Authorizer(c, MemberPrincipal(task["org_id"], task["execution_authorized_by"]))
        )
        if result != expected:
            raise TaskError("INVALID_INPUT")
        insert(
            c,
            "insight_reports",
            task["org_id"],
            feedback_id=result["feedback_id"],
            task_id=task["id"],
            schema_version=1,
            body=result["body"],
        )


def submit_insight(c, p, feedback_id, handler):
    refresh(c, p)
    lock_org(c, p.org_id)
    parent = row(c, "feedback_snapshots", p.org_id, feedback_id)
    snap = row(c, "intelligence_snapshots", p.org_id, parent["snapshot_id"])
    owner = row(c, "tasks", p.org_id, parent["task_id"])
    existing = c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND kind='intelligence.insight' AND idempotency_key=%s",
        (p.org_id, str(feedback_id)),
    ).scalar_one_or_none()
    if existing:
        handler.freeze(c, row(c, "tasks", p.org_id, existing), Authorizer(c, p))
        return existing
    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "intelligence.insight",
        "handler_version": "1",
        "business_code": snap["business_code"],
        "source_id": owner["source_id"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_external_calls": 0,
        "max_attempts": 1,
        "idempotency_key": str(feedback_id),
    }
    values["input_sha256"] = input_digest(
        values, handler.freeze(c, values, Authorizer(c, p), feedback_id=feedback_id)
    )
    create_task(c, values, [{"role": "feedback", "feedback_id": feedback_id}])
    return tid


def latest_insight(c, p, business, day):
    refresh(c, p)
    # Select the newest exact-day object before authorization; never fall back after withdrawal.
    value = (
        c.exec_driver_sql(
            "SELECT i.* FROM insight_reports i JOIN feedback_snapshots f ON f.id=i.feedback_id AND f.org_id=i.org_id JOIN intelligence_snapshots s ON s.id=f.snapshot_id AND s.org_id=f.org_id JOIN tasks t ON t.id=i.task_id AND t.org_id=i.org_id WHERE i.org_id=%s AND s.business_code=%s AND s.business_date=%s AND t.state='succeeded' ORDER BY i.created_at DESC,i.id DESC LIMIT 1",
            (p.org_id, business, day),
        )
        .mappings()
        .one_or_none()
    )
    if not value:
        return None
    try:
        full = read_feedback(c, p, value["feedback_id"])
    except Denied as exc:
        if exc.code == "NOT_FOUND":
            return None
        raise
    if value["schema_version"] != 1 or value["body"] != derive([full]):
        raise Denied("SOURCE_UNAVAILABLE")
    return {
        "id": value["id"],
        "created_at": value["created_at"],
        "business_code": business,
        "business_date": day,
        "feedback_id": value["feedback_id"],
        "version_no": full["version_no"],
        **{k: v for k, v in value["body"].items() if k != "source_claim_ids"},
    }
