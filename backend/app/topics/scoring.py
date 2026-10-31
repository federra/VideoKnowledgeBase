"""One-call exact-revision scoring with immutable, source-authorized publication."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.collection.service import insert
from app.core.repository import create_task
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import MemberPrincipal
from app.security.storage import audit, receipt
from app.tasks.service import TaskError, input_digest
from app.topics import service
from app.topics.execution import execute_call, stored_output
from app.topics.score_contracts import ScoreResult
from app.topics.score_model import (
    LEGACY_RUBRIC,
    RUBRIC,
    legacy_system_prompt,
    system_prompt,
    validate_legacy_score,
    validate_score,
)

KIND = "topic.score"
VERSION = "2"


def jsonable(value):
    return json.loads(json.dumps(value, default=str))


def ready(c, p, business):
    """Read-only readiness: no model invocation and no requirement to possess write access."""
    from app.model_config.service import STAGES, binding, credential_ready, get

    if business != "motion_comic":
        return False
    head = binding(c, p.org_id, business)
    sid = head["bindings"].get("topic_score") if head else None
    source = get(c, "model_sources", p.org_id, UUID(sid)) if sid else None
    if not source or not source["enabled"] or source["capability"] != STAGES["topic_score"]:
        return False
    rev = get(c, "ai_config_revisions", p.org_id, source["config_revision_id"])
    conn = get(c, "provider_connections", p.org_id, source["connection_id"])
    if not rev or not conn or not conn["enabled"]:
        return False
    cfg = rev["parameters"]
    return bool(
        source["capability"] == "text"
        and cfg.get("provider") in ("openai", "deepseek")
        and conn["provider_code"] == cfg.get("provider")
        and conn["secret_ref"] == cfg.get("secret_ref")
        and credential_ready(cfg.get("secret_ref", ""))
    )


class Score:
    version = VERSION
    rubric = RUBRIC
    validator = staticmethod(validate_score)
    prompt = staticmethod(system_prompt)
    action = "content.write"

    def __init__(self, model=None, store=None):
        self.model, self.store = model, store

    def freeze(self, c, task, az):
        from app.model_config import resolve

        service.authorize(c, az.p, task["business_code"], "content.write")
        if task["business_code"] != "motion_comic":
            raise TaskError("INVALID_INPUT")
        raw = az.check("raw_assets", task["raw_asset_id"], "content.write")
        data = json.loads(raw["body_text"])
        if (
            task["kind"] != KIND
            or task["handler_version"] != self.version
            or task["max_attempts"] != 1
            or task["max_external_calls"] != 1
            or raw["submitted_by"] != task["requested_by"]
            or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
            or data["rubric_version"] != self.rubric
            or data["business_code"] != task["business_code"]
        ):
            raise TaskError("INVALID_INPUT")
        card = service.row(c, az.p, "topic_cards", UUID(data["topic_id"]))
        revision = service.row(c, az.p, "topic_revisions", UUID(data["revision_id"]))
        if card["current_revision_id"] != revision["id"]:
            raise TaskError("INVALID_INPUT")
        if (
            revision["topic_id"] != card["id"]
            or card["business_code"] != task["business_code"]
            or revision["version_no"] != data["topic_version"]
            or revision["fields"] != data["fields"]
            or revision["source_refs"] != data["source_refs"]
            or revision["content_sha256"] != data["fields_sha256"]
            or digest(data["fields"]) != data["fields_sha256"]
        ):
            raise TaskError("INVALID_INPUT")
        service.check_sources(c, az.p, data["source_refs"])
        if digest(jsonable(resolve(c, az.p, task["business_code"], "topic_score"))) != digest(
            data["config"]
        ):
            raise TaskError("MODEL_NOT_CONFIGURED")
        return data

    def execute_ticket(self, runner, ticket, checkpoint):
        data = ticket.payload
        return execute_call(
            runner,
            ticket,
            checkpoint,
            data["config"],
            self.prompt(),
            json.dumps(
                {"fields": data["fields"], "rubric_version": self.rubric, "market_evidence": []},
                ensure_ascii=False,
            ),
            ScoreResult.model_json_schema(),
            invocation_no=1,
            prompt_version=f"topic.score/v{self.version}",
            validator=self.validator,
            model=self.model,
            store=self.store,
        )

    def publish(self, c, task, result):
        p = MemberPrincipal(task["org_id"], task["execution_authorized_by"])
        data = self.freeze(c, task, Authorizer(c, p))
        value = stored_output(
            c, p, task["id"], UUID(result["execution_id"]), self.validator, store=self.store
        )
        if value != result["output"]:
            raise TaskError("INVALID_RESPONSE")
        insert(
            c,
            "topic_assessments",
            p.org_id,
            topic_id=UUID(data["topic_id"]),
            topic_revision_id=UUID(data["revision_id"]),
            task_id=task["id"],
            ai_execution_id=UUID(result["execution_id"]),
            rubric_version=self.rubric,
            body=value,
            created_by=p.member_id,
        )
        audit(c, p.org_id, p.member_id, "topic.scored", "topic", UUID(data["topic_id"]))


class LegacyScore(Score):
    version = "1"
    rubric = LEGACY_RUBRIC
    validator = staticmethod(validate_legacy_score)
    prompt = staticmethod(legacy_system_prompt)


def start(c, p, key, ident, request, handler=None):
    from app.model_config import resolve

    card = service.row(c, p, "topic_cards", ident)
    service.authorize(c, p, card["business_code"], "content.write")
    if card["business_code"] != "motion_comic":
        raise Denied("RUBRIC_UNAVAILABLE")
    handler = handler or Score()

    def perform():
        card = service.row(c, p, "topic_cards", ident)
        revision = service.row(c, p, "topic_revisions", card["current_revision_id"])
        if request.expected_version != revision["version_no"]:
            raise Denied("VERSION_CONFLICT")
        service.check_sources(c, p, revision["source_refs"])
        # Receipt holds the organization lock, making this per-revision gate atomic.
        if c.exec_driver_sql(
            "SELECT 1 FROM tasks t JOIN raw_assets r ON r.org_id=t.org_id AND r.id=t.raw_asset_id WHERE t.org_id=%s AND t.kind=%s AND r.body_text::jsonb->>'revision_id'=%s AND t.state IN ('queued','running','cancel_requested')",
            (p.org_id, KIND, str(revision["id"])),
        ).first():
            raise Denied("VERSION_CONFLICT")
        cfg = jsonable(resolve(c, p, card["business_code"], "topic_score"))
        data = {
            "topic_id": str(ident),
            "revision_id": str(revision["id"]),
            "topic_version": revision["version_no"],
            "fields": revision["fields"],
            "fields_sha256": revision["content_sha256"],
            "source_refs": revision["source_refs"],
            "rubric_version": handler.rubric,
            "business_code": card["business_code"],
            "config": cfg,
        }
        text = json.dumps(data, sort_keys=True, ensure_ascii=False)
        raw = insert(
            c,
            "raw_assets",
            p.org_id,
            origin="manual",
            asset_kind="response",
            submitted_by=p.member_id,
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        tid = uuid4()
        values = {
            "id": tid,
            "org_id": p.org_id,
            "kind": KIND,
            "handler_version": handler.version,
            "business_code": card["business_code"],
            "raw_asset_id": raw,
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": 1,
            "idempotency_key": "topic-score/" + str(p.member_id) + "/" + str(key),
        }
        values["input_sha256"] = input_digest(values, handler.freeze(c, values, Authorizer(c, p)))
        create_task(
            c,
            values,
            [
                {"role": "topic_score_input", "raw_asset_id": raw},
                {"role": "model", "ai_config_revision_id": UUID(cfg["revision_id"])},
            ],
        )
        audit(c, p.org_id, p.member_id, "topic.score.requested", "task", tid)
        return {"id": str(tid)}

    saved = receipt(
        c, p, "evaluateTopic", key, {"id": str(ident), **request.model_dump(mode="json")}, perform
    )
    return read(c, p, UUID(saved["id"]))


def assessment_view(c, p, assessment):
    r = service.row(c, p, "topic_revisions", assessment["topic_revision_id"])
    return dict(
        id=assessment["id"],
        topic_version=r["version_no"],
        rubric_version=assessment["rubric_version"],
        created_at=assessment["created_at"],
        market_basis="ai_inference" if assessment["rubric_version"] == RUBRIC else "unavailable",
        **assessment["body"],
    )


def read(c, p, ident):
    task = service.row(c, p, "tasks", ident)
    if task["kind"] != KIND:
        raise Denied("NOT_FOUND")
    service.authorize(c, p, task["business_code"])
    data = json.loads(
        Authorizer(c, p).check("raw_assets", task["raw_asset_id"], "content.read")["body_text"]
    )
    service.check_sources(c, p, data["source_refs"])
    a = (
        c.exec_driver_sql(
            "SELECT * FROM topic_assessments WHERE org_id=%s AND task_id=%s", (p.org_id, ident)
        )
        .mappings()
        .one_or_none()
    )
    return {
        "id": ident,
        "task_id": ident,
        "state": task["state"],
        "safe_error_code": task["safe_error_code"],
        "topic_id": data["topic_id"],
        "topic_version": data["topic_version"],
        "assessment": assessment_view(c, p, a) if a else None,
    }


def projection(c, p, card, revision):
    task = c.exec_driver_sql(
        "SELECT t.id FROM tasks t JOIN raw_assets r ON r.org_id=t.org_id AND r.id=t.raw_asset_id WHERE t.org_id=%s AND t.kind=%s AND r.body_text::jsonb->>'revision_id'=%s ORDER BY t.created_at DESC,t.id DESC LIMIT 1",
        (p.org_id, KIND, str(revision["id"])),
    ).scalar_one_or_none()
    view = read(c, p, task) if task else None
    assessment = view["assessment"] if view else None
    status = "needs_review" if revision["version_no"] > 1 else "not_evaluated"
    if view:
        status = {
            "queued": "pending",
            "running": "scoring",
            "cancel_requested": "scoring",
            "failed": "failed",
            "cancelled": "failed",
            "succeeded": "insufficient_evidence"
            if not assessment or assessment["total"] is None
            else "scored",
        }[view["state"]]
    return {
        "evaluation_status": status,
        "assessment": assessment,
        "evaluation_task": view,
        "score_model_ready": ready(c, p, card["business_code"]),
    }
