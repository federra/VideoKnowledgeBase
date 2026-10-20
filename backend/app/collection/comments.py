"""Explicit one-off capture of an unknown provider comment shape, with durable evidence.

No normalization, empty-comment assertion, feedback creation, or model call here.
"""

import re
from uuid import UUID, uuid4

from sqlalchemy import select

from app.collection.handler import Collect
from app.collection.service import get, insert
from app.connectors.tikhub import CAPABILITY, VERSION
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import authorized, row, shanghai_date
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, receipt
from app.tasks.service import TaskError, input_digest


def target(c, p, entry_id):
    entry = row(c, "snapshot_entries", p.org_id, entry_id)
    snap = row(c, "intelligence_snapshots", p.org_id, entry["snapshot_id"])
    today = c.exec_driver_sql(
        "SELECT (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date"
    ).scalar_one()
    if (
        not snap["sealed_at"]
        or snap["business_date"] != today
        or not entry["content_observation_id"]
    ):
        raise Denied("DATE_WINDOW_MISMATCH")
    authorized(c, p, snap)
    obs = row(c, "content_observations", p.org_id, entry["content_observation_id"])
    content = row(c, "external_contents", p.org_id, obs["content_id"])
    if content["platform_code"] != "douyin" or not re.fullmatch(
        r"[0-9]{1,32}", content["platform_content_id"]
    ):
        raise Denied("VALIDATION_FAILED")
    return entry, snap, content


class Capture(Collect):
    def __init__(self, connector):
        super().__init__(connector, min_interval=0)

    def freeze(self, c, task, az, *, snapshot_id=None):
        org = task["org_id"]
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, task["id"])
            )
            .mappings()
            .one()
        )
        source = az.require("sources", job["source_id"], self.action)
        connection = get(c, "provider_connections", org, job["connection_id"])
        if (
            not source["enabled"]
            or source["target_kind"] != "content"
            or not connection
            or not connection["enabled"]
            or connection["provider_code"] != "tikhub"
            or connection["secret_ref"] != "TIKHUB_API_KEY"
            or job["capability_code"] != CAPABILITY
            or job["connector_version"] != VERSION
            or job["plan_id"] is not None
            or job["max_requests"] != 1
            or job["max_items"] != 20
            or task["max_external_calls"] != 1
            or digest(job["safe_request"]) != job["request_sha256"]
        ):
            raise TaskError("INVALID_INPUT")
        if snapshot_id is None:
            inputs = (
                c.exec_driver_sql(
                    "SELECT * FROM task_inputs WHERE org_id=%s AND task_id=%s", (org, task["id"])
                )
                .mappings()
                .all()
            )
            if len(inputs) != 1 or not inputs[0]["snapshot_id"]:
                raise TaskError("INVALID_INPUT")
            snapshot_id = inputs[0]["snapshot_id"]
        snap = row(c, "intelligence_snapshots", org, snapshot_id)
        authorized(c, az.p, snap)
        e, o = metadata.tables["snapshot_entries"], metadata.tables["content_observations"]
        entries = (
            c.execute(
                select(e.c.id)
                .join(o, (o.c.id == e.c.content_observation_id) & (o.c.org_id == e.c.org_id))
                .where(
                    e.c.org_id == org,
                    e.c.snapshot_id == snapshot_id,
                    o.c.content_id == source["content_id"],
                )
            )
            .scalars()
            .all()
        )
        if len(entries) != 1:
            raise TaskError("INVALID_INPUT")
        _, snap, content = target(c, az.p, entries[0])
        expected = {"aweme_id": content["platform_content_id"], "cursor": 0, "count": 20}
        if (
            job["safe_request"] != expected
            or job["business_date"] != snap["business_date"]
            or job["business_code"] != snap["business_code"]
            or source["business_code"] != snap["business_code"]
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "snapshot_id": str(snapshot_id),
            "entry_id": str(entries[0]),
            "source_version": source["lock_version"],
            "connection_version": connection["lock_version"],
            "request": expected,
            "capability": CAPABILITY,
            "maximum": 20,
            "business_date": str(job["business_date"]),
        }

    def publish(self, c, task, result):
        org = task["org_id"]
        raw = get(c, "raw_assets", org, UUID(result["raw_asset_id"]))
        call = get(c, "collection_calls", org, UUID(result["call_id"]))
        job = get(c, "collection_jobs", org, raw["collection_job_id"])
        if (
            job["task_id"] != task["id"]
            or call["job_id"] != job["id"]
            or raw["collection_call_id"] != call["id"]
            or call["outcome"] != "success"
            or shanghai_date(raw["captured_at"]) != job["business_date"]
        ):
            raise TaskError("INVALID_INPUT")
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=org,
                task_id=task["id"],
                position=0,
                role="unmapped_comment_response",
                raw_asset_id=raw["id"],
            )
        )
        audit(
            c,
            org,
            task["execution_authorized_by"],
            "comments.response_captured",
            "raw_asset",
            raw["id"],
        )


def submit_capture(c, p, entry_id, key, handler):
    refresh(c, p)
    try:
        UUID(str(key))
    except ValueError:
        raise Denied("VALIDATION_FAILED") from None
    _entry, snap, content = target(c, p, entry_id)
    az = Authorizer(c, p)
    if not az.allowed("source.configure", {("org", str(p.org_id))}) or not az.allowed(
        "collection.run", {("org", str(p.org_id)), ("business", snap["business_code"])}
    ):
        raise Denied("ACCESS_DENIED")

    def perform():
        # A different HTTP key cannot purchase another page for this entry by accident.
        prior = c.exec_driver_sql(
            "SELECT 1 FROM collection_jobs j JOIN task_inputs i ON i.task_id=j.task_id AND i.org_id=j.org_id JOIN sources s ON s.id=j.source_id AND s.org_id=j.org_id WHERE j.org_id=%s AND j.capability_code=%s AND i.snapshot_id=%s AND s.content_id=%s LIMIT 1",
            (p.org_id, CAPABILITY, snap["id"], content["id"]),
        ).first()
        if prior:
            raise Denied("IDEMPOTENCY_CONFLICT")
        provider = (
            c.exec_driver_sql(
                "SELECT id,secret_ref,enabled FROM provider_connections WHERE org_id=%s AND provider_code='tikhub' ORDER BY created_at,id LIMIT 1",
                (p.org_id,),
            )
            .mappings()
            .one_or_none()
        )
        if provider and (provider["secret_ref"] != "TIKHUB_API_KEY" or not provider["enabled"]):
            raise Denied("SOURCE_UNAVAILABLE")
        connection = (
            provider["id"]
            if provider
            else insert(
                c,
                "provider_connections",
                p.org_id,
                name="TikHub 评论首采",
                provider_code="tikhub",
                secret_ref="TIKHUB_API_KEY",
                enabled=True,
            )
        )
        source = insert(
            c,
            "sources",
            p.org_id,
            name="评论首采：" + str(entry_id),
            business_code=snap["business_code"],
            platform_code="douyin",
            target_kind="content",
            content_id=content["id"],
            created_by=p.member_id,
            enabled=True,
        )
        task_id = uuid4()
        request = {"aweme_id": content["platform_content_id"], "cursor": 0, "count": 20}
        job = insert(
            c,
            "collection_jobs",
            p.org_id,
            source_id=source,
            connection_id=connection,
            task_id=task_id,
            capability_code=CAPABILITY,
            connector_version=VERSION,
            business_code=snap["business_code"],
            business_date=snap["business_date"],
            safe_request=request,
            request_sha256=digest(request),
            max_requests=1,
            max_items=20,
        )
        values = {
            "id": task_id,
            "org_id": p.org_id,
            "kind": "collect.tikhub-comments",
            "handler_version": VERSION,
            "source_id": source,
            "business_code": snap["business_code"],
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": 1,
            "idempotency_key": str(p.member_id) + ":" + key,
        }
        values["input_sha256"] = input_digest(
            values, handler.freeze(c, values, az, snapshot_id=snap["id"])
        )
        create_task(c, values, [{"role": "material", "snapshot_id": snap["id"]}])
        audit(c, p.org_id, p.member_id, "comments.capture_submitted", "task", task_id)
        return {
            "task_id": str(task_id),
            "job_id": str(job),
            "source_id": str(source),
            "entry_id": str(entry_id),
        }

    return receipt(
        c, p, "captureComments", key, {"entry_id": str(entry_id), "cursor": 0, "count": 20}, perform
    )
