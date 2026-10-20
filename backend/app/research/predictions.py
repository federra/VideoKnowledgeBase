"""Versioned prediction drafts and two-transaction immutable freeze confirmation."""

from decimal import Decimal
from uuid import UUID

from app.collection.service import insert
from app.core.repository import compare_and_swap
from app.intelligence.service import row
from app.research.inputs import read_input
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt


def wire(value):
    return {
        k: str(v) if isinstance(v, (UUID, Decimal)) else v
        for k, v in value.items()
        if k != "freeze_transaction"
    }


def exposure(c, p, input_id):
    # Observed evidence remains observed even if the API/UI hides its numeric metrics.
    seen = c.exec_driver_sql(
        "WITH RECURSIVE chain(node) AS (SELECT 'v:'||artifact_version_id::text FROM input_set_items WHERE org_id=%s AND input_set_id=%s UNION SELECT e.parent FROM chain c JOIN cip_graph_edges(%s) e ON e.child=c.node) SELECT EXISTS(SELECT 1 FROM chain c JOIN raw_assets r ON c.node='r:'||r.id::text WHERE r.org_id=%s AND r.collection_job_id IS NOT NULL)",
        (p.org_id, input_id, p.org_id, p.org_id),
    ).scalar_one()
    return ("retrospective", "observed") if seen else ("unknown", "unknown")


def draft_access(c, p, ident, action="content.read"):
    refresh(c, p)
    draft = row(c, "prediction_drafts", p.org_id, ident)
    read_input(c, p, draft["input_set_id"], action)
    return draft


def read_draft(c, p, ident):
    value = wire(draft_access(c, p, ident))
    value["lock_version"] = str(value["lock_version"])
    return value


def draft_values(c, p, request):
    frozen = read_input(c, p, request.input_set_id, "prediction.edit")
    metric = row(c, "metric_specs", p.org_id, request.metric_spec_id)
    if not metric:
        raise Denied("NOT_FOUND")
    if request.account_id:
        account = row(c, "external_accounts", p.org_id, request.account_id)
        if account["platform_code"] != request.platform_code:
            raise Denied("VALIDATION_FAILED")
    if request.supersedes_prediction_id:
        old = read_prediction(c, p, request.supersedes_prediction_id)
        previous = read_input(c, p, old["input_set_id"])
        if previous["work_id"] != frozen["work_id"]:
            raise Denied("VALIDATION_FAILED")
    context, exposed = exposure(c, p, frozen["id"])
    values = request.model_dump(exclude={"expected_lock_version"})
    values.update(
        author_kind="human",
        author_member_id=p.member_id,
        ai_execution_id=None,
        context_kind=context,
        outcome_exposure=exposed,
        rubric_revision_id=None,
        prompt_revision_id=None,
    )
    values["window_start_offset_seconds"] = int(values["window_start_offset_seconds"])
    values["window_end_offset_seconds"] = int(values["window_end_offset_seconds"])
    return values


def create_draft(c, p, key, request):
    refresh(c, p)
    lock_org(c, p.org_id)
    values = draft_values(c, p, request)
    saved = receipt(
        c,
        p,
        "createPredictionDraft",
        key,
        request.model_dump(mode="json"),
        lambda: {"id": str(insert(c, "prediction_drafts", p.org_id, **values))},
    )
    return read_draft(c, p, UUID(saved["id"]))


def update_draft(c, p, key, ident, request):
    refresh(c, p)
    lock_org(c, p.org_id)
    old = draft_access(c, p, ident, "prediction.edit")
    values = draft_values(c, p, request)
    # A revision cannot move a draft into a different work.
    before = read_input(c, p, old["input_set_id"])
    after = read_input(c, p, request.input_set_id)
    if before["work_id"] != after["work_id"]:
        raise Denied("VALIDATION_FAILED")

    def perform():
        if old["lock_version"] != int(request.expected_lock_version):
            raise Denied("VERSION_CONFLICT")
        compare_and_swap(c, "prediction_drafts", p.org_id, ident, old["lock_version"], values)
        return {"id": str(ident)}

    saved = receipt(
        c, p, "updatePredictionDraft:" + str(ident), key, request.model_dump(mode="json"), perform
    )
    return read_draft(c, p, UUID(saved["id"]))


def read_prediction(c, p, ident):
    refresh(c, p)
    value = Authorizer(c, p).read("predictions", ident)
    events = {
        e["event_kind"]: e["occurred_at"]
        for e in c.exec_driver_sql(
            "SELECT event_kind,occurred_at FROM prediction_events WHERE org_id=%s AND prediction_id=%s",
            (p.org_id, ident),
        ).mappings()
    }
    return {
        **wire(value),
        "draft_lock_version": str(value["draft_lock_version"]),
        "window_start_offset_seconds": str(value["window_start_offset_seconds"]),
        "window_end_offset_seconds": str(value["window_end_offset_seconds"]),
        "confirmed_at": events.get("freeze_confirmed"),
        "retracted_at": events.get("retracted"),
    }


def freeze_prediction(c, p, key, ident, expected):
    refresh(c, p)
    lock_org(c, p.org_id)
    draft = draft_access(c, p, ident, "prediction.freeze")

    def perform():
        if draft["lock_version"] != int(expected):
            raise Denied("VERSION_CONFLICT")
        if draft["reliability"] != "estimable":
            raise Denied("INSUFFICIENT_MATERIAL")
        previous = c.exec_driver_sql(
            "SELECT id FROM predictions WHERE org_id=%s AND draft_id=%s AND draft_lock_version=%s",
            (p.org_id, ident, draft["lock_version"]),
        ).scalar_one_or_none()
        if previous:
            return {"id": str(previous)}
        # New observed evidence can only downgrade exposure. Never upgrade to prospective.
        _now_context, now_exposure = exposure(c, p, draft["input_set_id"])
        if now_exposure == "observed" and draft["outcome_exposure"] != "observed":
            raise Denied("VERSION_CONFLICT")
        values = {
            k: v
            for k, v in draft.items()
            if k not in ("id", "org_id", "created_at", "updated_at", "lock_version", "reliability")
        }
        pred = insert(
            c,
            "predictions",
            p.org_id,
            **values,
            draft_id=ident,
            draft_lock_version=draft["lock_version"],
            frozen_by=p.member_id,
            content_sha256=digest(wire(values)),
        )
        c.exec_driver_sql("SELECT cip_seal('predictions',%s,%s)", (p.org_id, pred))
        audit(c, p.org_id, p.member_id, "prediction.frozen", "prediction", pred)
        return {"id": str(pred)}

    saved = receipt(
        c,
        p,
        "freezePrediction:" + str(ident),
        key,
        {"expected_lock_version": str(expected)},
        perform,
    )
    return read_prediction(c, p, UUID(saved["id"]))


def confirm_prediction(c, p, ident):
    refresh(c, p)
    lock_org(c, p.org_id)
    value = read_prediction(c, p, ident)
    read_input(c, p, value["input_set_id"], "prediction.freeze")
    if value["frozen_by"] != str(p.member_id):
        raise Denied("NOT_FOUND")
    if not value["confirmed_at"]:
        insert(
            c,
            "prediction_events",
            p.org_id,
            prediction_id=ident,
            event_kind="freeze_confirmed",
            reason="首次冻结事务已提交，服务端追加确认",
            actor_member_id=p.member_id,
        )
    return read_prediction(c, p, ident)


def retract_prediction(c, p, key, ident, reason):
    refresh(c, p)
    lock_org(c, p.org_id)
    value = read_prediction(c, p, ident)
    read_input(c, p, value["input_set_id"], "prediction.retract")
    if not reason.strip():
        raise Denied("VALIDATION_FAILED")

    def perform():
        if not value["retracted_at"]:
            insert(
                c,
                "prediction_events",
                p.org_id,
                prediction_id=ident,
                event_kind="retracted",
                reason=reason,
                actor_member_id=p.member_id,
            )
        return {"id": str(ident)}

    receipt(c, p, "retractPrediction:" + str(ident), key, {"reason": reason}, perform)
    return read_prediction(c, p, ident)
