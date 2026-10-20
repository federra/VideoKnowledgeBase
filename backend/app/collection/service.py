"""Explicit source configuration and permission checked, idempotent submission."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import JSON, null, select

from app.connectors.redfox import (
    CAPABILITIES,
    DAILY_BOARD,
    KEYWORD_DEFAULT,
    KEYWORD_WORKS,
    VERSION,
    identifier,
    item_limit,
)
from app.core.models import metadata
from app.core.repository import create_task
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, receipt
from app.tasks.service import input_digest


def get(c, name, org, ident):
    t = metadata.tables[name]
    return c.execute(select(t).where(t.c.org_id == org, t.c.id == ident)).mappings().one_or_none()


def insert(c, table_name, org, **values):
    ident = values.pop("id", uuid4())
    table = metadata.tables[table_name]
    values = {
        key: null() if value is None and isinstance(table.c[key].type, JSON) else value
        for key, value in values.items()
    }
    c.execute(table.insert().values(id=ident, org_id=org, **values))
    return ident


def configure_connection(c, p, name):
    refresh(c, p)
    if not Authorizer(c, p).allowed("source.configure", {("org", str(p.org_id))}):
        raise Denied("ACCESS_DENIED")
    t = metadata.tables["provider_connections"]
    old = (
        c.execute(select(t).where(t.c.org_id == p.org_id, t.c.name == name))
        .mappings()
        .one_or_none()
    )
    if old:
        if old["provider_code"] != "redfox" or old["secret_ref"] != "REDFOX_API_KEY":
            raise Denied("VALIDATION_FAILED")
        return old["id"]
    ident = insert(
        c,
        "provider_connections",
        p.org_id,
        name=name,
        provider_code="redfox",
        secret_ref="REDFOX_API_KEY",
        enabled=True,
    )
    audit(c, p.org_id, p.member_id, "connection.configured", "provider_connection", ident)
    return ident


def identity(c, table, org, field, value, *, platform="douyin", **values):
    t = metadata.tables[table]
    old = (
        c.execute(
            select(t).where(t.c.org_id == org, t.c.platform_code == platform, t.c[field] == value)
        )
        .mappings()
        .one_or_none()
    )
    if old:
        if (
            table == "external_contents"
            and old["account_id"]
            and values.get("account_id")
            and old["account_id"] != values["account_id"]
        ):
            from app.tasks.service import TaskError

            raise TaskError("INVALID_RESPONSE")
        return old["id"]
    return insert(c, table, org, platform_code=platform, **{field: value}, **values)


def configure_source(c, p, name, kind, value, *, enabled=False):
    refresh(c, p)
    if not Authorizer(c, p).allowed(
        "source.configure", {("org", str(p.org_id)), ("business", "motion_comic")}
    ):
        raise Denied("ACCESS_DENIED")
    if kind not in ("keyword", "account", "board"):
        raise Denied("VALIDATION_FAILED")
    identifier(value)
    if kind == "board" and value != "小剧场":
        raise Denied("VALIDATION_FAILED")
    target = (
        {"keyword": value}
        if kind == "keyword"
        else {"board_code": value}
        if kind == "board"
        else {"account_id": identity(c, "external_accounts", p.org_id, "platform_uid", value)}
    )
    return insert(
        c,
        "sources",
        p.org_id,
        name=name,
        business_code="motion_comic",
        platform_code="douyin",
        target_kind=kind,
        enabled=enabled,
        created_by=p.member_id,
        **target,
    )


def accepted(c, org, job, *, reused=False):
    t = get(c, "tasks", org, job["task_id"])
    return {
        "resource_id": str(job["id"]),
        "task": {
            "task_id": str(t["id"]),
            "state": t["state"],
            "lock_version": str(t["lock_version"]),
        },
        "reused_existing_task": reused,
    }


def submit(c, p, request, key, handler, *, plan=None, scheduled_for=None):
    refresh(c, p)
    source = Authorizer(c, p).require("sources", request.source_id, "collection.run")
    if (
        request.max_requests != 1
        or not 1 <= request.max_items <= item_limit(request.capability_code)
        or request.capability_code not in CAPABILITIES
    ):
        raise Denied("VALIDATION_FAILED")

    created = False

    def perform():
        nonlocal created
        created = True
        connection = get(c, "provider_connections", p.org_id, request.provider_connection_id)
        if (
            not source["enabled"]
            or not connection
            or not connection["enabled"]
            or connection["provider_code"] != "redfox"
            or connection["secret_ref"] != "REDFOX_API_KEY"
        ):
            raise Denied("VALIDATION_FAILED")
        expected_kind = CAPABILITIES[request.capability_code][1]
        if source["platform_code"] != "douyin" or source["target_kind"] != expected_kind:
            raise Denied("VALIDATION_FAILED")
        tid = uuid4()
        day = c.exec_driver_sql(
            "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date"
        ).scalar_one()
        if scheduled_for is not None:
            from zoneinfo import ZoneInfo

            day = scheduled_for.astimezone(ZoneInfo("Asia/Shanghai")).date()
        if request.capability_code == DAILY_BOARD:
            if source["board_code"] != "小剧场":
                raise Denied("VALIDATION_FAILED")
            data_day = (day - timedelta(days=1)).isoformat()
            params = {"type": "小剧场", "startTime": data_day, "endTime": data_day}
        elif request.capability_code == KEYWORD_DEFAULT:
            if source["keyword"] != "漫剧":
                raise Denied("VALIDATION_FAILED")
            params = {"keyword": "漫剧", "offset": 0, "sortType": "_0"}
        elif request.capability_code == KEYWORD_WORKS:
            if source["keyword"] != "漫剧":
                raise Denied("VALIDATION_FAILED")
            params = {
                "keyword": source["keyword"],
                "exactMatch": True,
                "pageNum": 1,
                "pageSize": request.max_items,
            }
        elif expected_kind == "keyword":
            params = {"keyword": source["keyword"], "offset": 0, "sortType": "_0"}
        else:
            account = get(c, "external_accounts", p.org_id, source["account_id"])
            params = {
                "userId": account["platform_uid"],
                "pageNum": 1,
                "pageSize": request.max_items,
            }
        jid = insert(
            c,
            "collection_jobs",
            p.org_id,
            source_id=source["id"],
            connection_id=connection["id"],
            task_id=tid,
            capability_code=request.capability_code,
            connector_version=VERSION,
            business_code=source["business_code"],
            business_date=day,
            safe_request=params,
            request_sha256=digest(params),
            max_requests=1,
            max_items=request.max_items,
            plan_id=plan["id"] if plan else None,
            scheduled_for=scheduled_for,
        )
        values = {
            "id": tid,
            "org_id": p.org_id,
            "kind": "collect.redfox",
            "handler_version": VERSION,
            "source_id": source["id"],
            "business_code": source["business_code"],
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": 1,
            "idempotency_key": str(p.member_id)
            + (":plan:" + str(plan["id"]) if plan else "")
            + ":"
            + key,
        }
        values["input_sha256"] = input_digest(values, handler.freeze(c, values, Authorizer(c, p)))
        create_task(c, values)
        audit(c, p.org_id, p.member_id, "collection.submitted", "task", tid)
        return {"job_id": str(jid)}

    saved = receipt(
        c,
        p,
        "scheduleCollection" if plan else "startCollection",
        key,
        {
            **request.model_dump(mode="json"),
            **(
                {"plan_id": str(plan["id"]), "scheduled_for": scheduled_for.isoformat()}
                if plan
                else {}
            ),
        },
        perform,
    )
    return accepted(
        c, p.org_id, get(c, "collection_jobs", p.org_id, UUID(saved["job_id"])), reused=not created
    )
