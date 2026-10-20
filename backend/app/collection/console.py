"""Safe console views and permission-checked configuration; no provider requests here."""

from uuid import UUID

from sqlalchemy import select

from app.collection.service import configure_connection, configure_source, get, insert
from app.connectors.redfox import VERSION, AdapterError, identifier
from app.contracts.models import ConsoleSource
from app.core.models import metadata
from app.core.repository import compare_and_swap
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import refresh
from app.security.storage import audit, receipt
from app.tasks.service import cancel, external_calls, retry

FREQUENCIES = {"daily_0900": "daily:09:00", "every_2h": "hours:2", "every_4h": "hours:4"}


def plan_for(c, org, source):
    return (
        c.exec_driver_sql(
            "SELECT * FROM collection_plans WHERE org_id=%s AND source_id=%s ORDER BY created_at,id",
            (org, source),
        )
        .mappings()
        .one_or_none()
    )


def source_view(c, p, ident):
    source = Authorizer(c, p).require("sources", ident, "source.configure")
    plan = plan_for(c, p.org_id, ident)
    target = {"kind": source["target_kind"]}
    target.update(
        {
            k: source[k]
            for k in ("keyword", "account_id", "content_id", "board_code")
            if source[k] is not None
        }
    )
    last = (
        c.exec_driver_sql(
            "SELECT t.state,t.finished_at FROM collection_jobs j JOIN tasks t ON t.id=j.task_id WHERE j.org_id=%s AND j.source_id=%s ORDER BY j.created_at DESC,j.id DESC LIMIT 1",
            (p.org_id, ident),
        )
        .mappings()
        .one_or_none()
    )
    data = {
        k: source[k]
        for k in (
            "id",
            "created_at",
            "updated_at",
            "lock_version",
            "name",
            "business_code",
            "platform_code",
            "enabled",
        )
    }
    data["lock_version"] = str(data["lock_version"])
    data["archived"] = source["archived_at"] is not None
    data.update(
        target=target,
        last_state=last["state"] if last else None,
        last_at=last["finished_at"] if last else None,
        plan=None,
    )
    if plan:
        data["plan"] = {
            k: plan[k] for k in ("id", "created_at", "lock_version", "enabled", "connection_id")
        }
        data["plan"]["lock_version"] = str(data["plan"]["lock_version"])
        data["plan"].update(
            frequency=next(k for k, v in FREQUENCIES.items() if v == plan["schedule_expression"]),
            purpose=plan["request_options"].get("purpose", "intelligence"),
            max_requests=plan["max_requests_per_run"],
            max_items=plan["max_items_per_run"],
        )
    return ConsoleSource.model_validate(data).model_dump(mode="json")


def create_source(c, p, body, key):
    refresh(c, p)
    az = Authorizer(c, p)
    if not az.allowed(
        "source.configure", {("org", str(p.org_id)), ("business", body.business_code)}
    ):
        raise Denied("ACCESS_DENIED")
    if body.business_code != "motion_comic":
        raise Denied("UNSUPPORTED_SOURCE")

    def perform():
        value = body.address.strip()
        kind = "account" if value.startswith("uid:") else "keyword"
        value = value[4:] if kind == "account" else value
        try:
            identifier(value)
        except AdapterError:
            raise Denied("VALIDATION_FAILED") from None
        if "://" in value or (kind == "keyword" and value != "漫剧"):
            raise Denied("UNSUPPORTED_SOURCE")
        if body.provider_connection_id:
            conn = get(c, "provider_connections", p.org_id, body.provider_connection_id)
            if (
                not conn
                or not conn["enabled"]
                or conn["provider_code"] != "redfox"
                or conn["secret_ref"] != "REDFOX_API_KEY"
            ):
                raise Denied("SOURCE_UNAVAILABLE")
            connection = conn["id"]
        else:
            candidates = list(
                c.exec_driver_sql(
                    "SELECT id FROM provider_connections WHERE org_id=%s AND enabled AND provider_code='redfox' AND secret_ref='REDFOX_API_KEY'",
                    (p.org_id,),
                ).scalars()
            )
            if len(candidates) > 1:
                raise Denied("VALIDATION_FAILED")
            connection = candidates[0] if candidates else configure_connection(c, p, "红狐")
        source = configure_source(c, p, body.name, kind, value)
        insert(
            c,
            "collection_plans",
            p.org_id,
            source_id=source,
            connection_id=connection,
            authorized_by=p.member_id,
            capability_code="douyin.creator.works"
            if kind == "account"
            else "douyin.keyword.default",
            connector_version=VERSION,
            schedule_expression=FREQUENCIES[body.frequency],
            max_requests_per_run=1,
            max_items_per_run=1,
            request_options={"purpose": body.purpose},
        )
        audit(c, p.org_id, p.member_id, "source.created", "source", source)
        return {"id": str(source)}

    saved = receipt(c, p, "createSource", key, body.model_dump(mode="json"), perform)
    return source_view(c, p, UUID(saved["id"]))


def patch_source(c, p, ident, body, key):
    refresh(c, p)
    source = Authorizer(c, p).require("sources", ident, "source.configure")

    def perform():
        if source["lock_version"] != int(body.expected_lock_version):
            raise Denied("VERSION_CONFLICT")
        plan = plan_for(c, p.org_id, ident)
        if body.enabled and source["archived_at"]:
            raise Denied("IMMUTABLE_INPUT")
        if body.enabled and plan:
            Authorizer(c, p).require("sources", ident, "collection.run")
            conn = get(c, "provider_connections", p.org_id, plan["connection_id"])
            if not conn or not conn["enabled"]:
                raise Denied("SOURCE_UNAVAILABLE")
            if plan["request_options"].get("purpose") in ("knowledge", "both") and not Authorizer(
                c, p
            ).allowed("knowledge.edit", Authorizer(c, p).scopes("sources", source)):
                raise Denied("ACCESS_DENIED")
        values = body.model_dump(exclude_none=True, exclude={"expected_lock_version"})
        archived = values.pop("archived", None)
        if archived is False:
            raise Denied("IMMUTABLE_INPUT")
        if archived:
            values.update(
                archived_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
                enabled=False,
            )
        compare_and_swap(c, "sources", p.org_id, ident, source["lock_version"], values)
        if (body.enabled is not None or archived) and plan:
            compare_and_swap(
                c,
                "collection_plans",
                p.org_id,
                plan["id"],
                plan["lock_version"],
                {"enabled": False if archived else body.enabled, "authorized_by": p.member_id},
            )
        audit(c, p.org_id, p.member_id, "source.updated", "source", ident)
        return {"id": str(ident)}

    receipt(c, p, "updateSource:" + str(ident), key, body.model_dump(mode="json"), perform)
    return source_view(c, p, ident)


def list_sources(c, p, business):
    refresh(c, p)
    az = Authorizer(c, p)
    rows = []
    for ident in c.exec_driver_sql(
        "SELECT id FROM sources WHERE org_id=%s AND business_code=%s AND archived_at IS NULL ORDER BY created_at DESC,id DESC",
        (p.org_id, business),
    ).scalars():
        try:
            rows.append(source_view(c, p, ident))
        except Denied as exc:
            if exc.code not in ("NOT_FOUND", "ACCESS_DENIED"):
                raise
    # Empty is only legitimate when current scope grants the list action.
    if not rows and not az.allowed(
        "source.configure", {("org", str(p.org_id)), ("business", business)}
    ):
        raise Denied("ACCESS_DENIED")
    return {"items": rows, "next_cursor": None, "total": str(len(rows))}


SAFE_CODES = {
    "INVALID_INPUT": "VALIDATION_FAILED",
    "ACCESS_REVOKED": "ACCESS_DENIED",
    "HANDLER_UNAVAILABLE": "SERVICE_NOT_READY",
    "LOCAL_TRANSIENT": "SERVICE_NOT_READY",
    "LEASE_LOST": "SERVICE_NOT_READY",
    "TIMEOUT": "SERVICE_NOT_READY",
}


def task_view(c, p, ident):
    refresh(c, p)
    az = Authorizer(c, p)
    row = get(c, "tasks", p.org_id, ident)
    if not row:
        raise Denied("NOT_FOUND")
    scopes = az.scopes("tasks", row)
    # Inherit only verified parent scopes, never a caller-supplied business label.
    for field, kind in (
        ("source_id", "sources"),
        ("work_id", "works"),
        ("raw_asset_id", "raw_assets"),
    ):
        if row[field]:
            scopes |= az.scopes(kind, az.row(kind, row[field]))
    if not az.allowed("task.read", scopes):
        raise Denied("NOT_FOUND")
    fields = (
        "kind",
        "business_code",
        "state",
        "business_outcome",
        "requested_by",
        "execution_authorized_by",
        "max_attempts",
        "max_external_calls",
        "available_at",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    )
    data = {k: row[k] for k in fields}
    data.update(
        id=str(row["id"]),
        lock_version=str(row["lock_version"]),
        safe_error_code=SAFE_CODES.get(row["safe_error_code"], row["safe_error_code"]),
        outputs=[],
    )
    # IDs are references, but still filter every output against present permissions.
    for out in c.execute(
        select(metadata.tables["task_outputs"]).where(
            metadata.tables["task_outputs"].c.task_id == ident
        )
    ).mappings():
        for kind, table in [
            ("raw_asset", "raw_assets"),
            ("report", "analysis_reports"),
            ("evaluation", "quality_evaluations"),
            ("prediction", "predictions"),
        ]:
            if out.get(kind + "_id"):
                try:
                    az.read(table, out[kind + "_id"])
                except Denied:
                    continue
                data["outputs"].append({"kind": kind, "id": str(out[kind + "_id"])})
        if out.get("snapshot_id"):
            snap = get(c, "intelligence_snapshots", p.org_id, out["snapshot_id"])
            try:
                az.read("sources", snap["source_id"])
            except Denied:
                continue
            data["outputs"].append({"kind": "snapshot", "id": str(snap["id"])})
    from app.contracts.models import Task

    return Task.model_validate(data).model_dump(mode="json")


def list_tasks(c, p, business):
    refresh(c, p)
    rows = []
    for ident in c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND business_code=%s ORDER BY created_at DESC,id DESC",
        (p.org_id, business),
    ).scalars():
        try:
            rows.append(task_view(c, p, ident))
        except Denied as exc:
            if exc.code != "NOT_FOUND":
                raise
    if not rows and not Authorizer(c, p).allowed(
        "task.read", {("org", str(p.org_id)), ("business", business)}
    ):
        raise Denied("ACCESS_DENIED")
    return {"items": rows, "next_cursor": None, "total": str(len(rows))}


def control_task(c, p, ident, body, runner, operation, key):
    from app.tasks.service import manage

    refresh(c, p)
    current = get(c, "tasks", p.org_id, ident)
    if not current:
        raise Denied("NOT_FOUND")
    task = manage(c, p, ident, current["lock_version"])

    def perform():
        if task["lock_version"] != int(body.expected_lock_version):
            raise Denied("VERSION_CONFLICT")
        if operation == "retry":
            if external_calls(c, ident):
                raise Denied("EXTERNAL_RESULT_UNKNOWN")
            if retry(c, p, ident, int(body.expected_lock_version), runner) != "queued":
                raise Denied("IMMUTABLE_INPUT")
        elif not cancel(c, p, ident, int(body.expected_lock_version)):
            raise Denied("VERSION_CONFLICT")
        return {"id": str(ident)}

    receipt(c, p, operation + "Task:" + str(ident), key, body.model_dump(mode="json"), perform)
    return task_view(c, p, task["id"])
