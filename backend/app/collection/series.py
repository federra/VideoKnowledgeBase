"""Capture an initially unknown series shape; retain evidence before offline mapping."""

from uuid import UUID, uuid4

from app.collection.handler import Collect
from app.collection.service import get, insert
from app.connectors.tikhub_series import CAPABILITY, REQUEST, VERSION
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, receipt
from app.tasks.service import TaskError, input_digest

BOARD_CODE = "tikhub-series-hot"


class CaptureSeries(Collect):
    def freeze(self, c, task, az):
        org = task["org_id"]
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, task["id"])
            )
            .mappings()
            .one()
        )
        source = az.require("sources", job["source_id"], self.action)
        conn = get(c, "provider_connections", org, job["connection_id"])
        if (
            not source["enabled"]
            or source["target_kind"] != "board"
            or source["board_code"] != BOARD_CODE
            or source["business_code"] != "motion_comic"
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "tikhub"
            or conn["secret_ref"] != "TIKHUB_API_KEY"
            or job["capability_code"] != CAPABILITY
            or job["connector_version"] != VERSION
            or job["plan_id"] is not None
            or job["safe_request"] != REQUEST
            or digest(job["safe_request"]) != job["request_sha256"]
            or job["max_requests"] != 1
            or job["max_items"] != 10
            or task["max_external_calls"] != 1
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "source_version": source["lock_version"],
            "connection_version": conn["lock_version"],
            "request": REQUEST,
            "capability": CAPABILITY,
            "maximum": 10,
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
                role="unmapped_series_response",
                raw_asset_id=raw["id"],
            )
        )
        audit(
            c,
            org,
            task["execution_authorized_by"],
            "series.response_captured",
            "raw_asset",
            raw["id"],
        )


def submit_capture(c, p, key, handler):
    refresh(c, p)
    az = Authorizer(c, p)
    for action in ["source.configure", "collection.run"]:
        if not az.allowed(action, {("org", str(p.org_id)), ("business", "motion_comic")}):
            raise TaskError("ACCESS_DENIED")

    def perform():
        if c.exec_driver_sql(
            "SELECT 1 FROM collection_jobs WHERE org_id=%s AND capability_code=%s AND business_date=%s",
            (p.org_id, CAPABILITY, shanghai_date()),
        ).first():
            raise TaskError("IDEMPOTENCY_CONFLICT")
        conn = (
            c.exec_driver_sql(
                "SELECT * FROM provider_connections WHERE org_id=%s AND provider_code='tikhub' ORDER BY created_at,id LIMIT 1",
                (p.org_id,),
            )
            .mappings()
            .one_or_none()
        )
        if conn and (not conn["enabled"] or conn["secret_ref"] != "TIKHUB_API_KEY"):
            raise TaskError("SOURCE_UNAVAILABLE")
        connection = (
            conn["id"]
            if conn
            else insert(
                c,
                "provider_connections",
                p.org_id,
                name="TikHub",
                provider_code="tikhub",
                secret_ref="TIKHUB_API_KEY",
                enabled=True,
            )
        )
        source = insert(
            c,
            "sources",
            p.org_id,
            name="TikHub短剧热榜 · content_type=0",
            business_code="motion_comic",
            platform_code="douyin",
            target_kind="board",
            board_code=BOARD_CODE,
            enabled=True,
            created_by=p.member_id,
        )
        tid = uuid4()
        job = insert(
            c,
            "collection_jobs",
            p.org_id,
            source_id=source,
            connection_id=connection,
            task_id=tid,
            capability_code=CAPABILITY,
            connector_version=VERSION,
            business_code="motion_comic",
            business_date=shanghai_date(),
            safe_request=REQUEST,
            request_sha256=digest(REQUEST),
            max_requests=1,
            max_items=10,
        )
        values = {
            "id": tid,
            "org_id": p.org_id,
            "kind": "collect.tikhub-series",
            "handler_version": VERSION,
            "source_id": source,
            "business_code": "motion_comic",
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": 1,
            "idempotency_key": str(p.member_id) + ":" + key,
        }
        values["input_sha256"] = input_digest(values, handler.freeze(c, values, az))
        create_task(c, values)
        return {"task_id": str(tid), "job_id": str(job), "source_id": str(source)}

    return receipt(c, p, "captureSeries", key, REQUEST, perform)


class NormalizeSeries:
    action = "collection.run"

    def freeze(self, c, task, az, *, raw_id=None):
        inputs = (
            [raw_id]
            if raw_id is not None
            else c.exec_driver_sql(
                "SELECT raw_asset_id FROM task_inputs WHERE org_id=%s AND task_id=%s ORDER BY position",
                (task["org_id"], task["id"]),
            )
            .scalars()
            .all()
        )
        if len(inputs) != 1 or not inputs[0] or task["max_external_calls"] != 0:
            raise TaskError("INVALID_INPUT")
        raw = az.read("raw_assets", inputs[0])
        job = get(c, "collection_jobs", task["org_id"], raw["collection_job_id"])
        source = az.require("sources", job["source_id"], self.action)
        call = get(c, "collection_calls", task["org_id"], raw["collection_call_id"])
        if (
            job["capability_code"] != CAPABILITY
            or job["connector_version"] != VERSION
            or job["safe_request"] != REQUEST
            or job["max_items"] != 10
            or source["board_code"] != BOARD_CODE
            or source["business_code"] != task["business_code"]
            or task["source_id"] != source["id"]
            or call["job_id"] != job["id"]
            or call["outcome"] != "success"
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "raw_id": str(raw["id"]),
            "sha256": raw["sha256"],
            "job_id": str(job["id"]),
            "source_version": source["lock_version"],
        }

    def execute(self, payload, checkpoint):
        checkpoint()
        return {"raw_id": payload["raw_id"]}

    def publish(self, c, task, result):
        import json

        from app.collection.handler import publish_batch
        from app.connectors.tikhub_series import normalize_series

        raw = get(c, "raw_assets", task["org_id"], UUID(result["raw_id"]))
        job = get(c, "collection_jobs", task["org_id"], raw["collection_job_id"])
        if shanghai_date(raw["captured_at"]) != job["business_date"]:
            raise TaskError("DATE_WINDOW_MISMATCH")
        batch = normalize_series(json.loads(raw["body_text"]))
        snapshot = publish_batch(c, task, raw, job, batch, record_output=False)
        import hashlib
        from datetime import UTC, datetime

        manifest = json.dumps(
            {"source_raw_id": str(raw["id"]), "snapshot_id": str(snapshot)}, sort_keys=True
        )
        derived = insert(
            c,
            "raw_assets",
            task["org_id"],
            origin="processing",
            asset_kind="response",
            processing_task_id=task["id"],
            parent_raw_asset_id=raw["id"],
            body_text=manifest,
            sha256=hashlib.sha256(manifest.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"],
                task_id=task["id"],
                position=0,
                role="series_normalization",
                raw_asset_id=derived,
            )
        )


def submit_normalization(c, p, raw_id):
    refresh(c, p)
    az = Authorizer(c, p)
    raw = az.read("raw_assets", raw_id)
    job = get(c, "collection_jobs", p.org_id, raw["collection_job_id"])
    az.require("sources", job["source_id"], "collection.run")
    if job["capability_code"] != CAPABILITY:
        raise TaskError("INVALID_INPUT")
    prior = c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND kind=%s AND idempotency_key=%s",
        (p.org_id, "series.normalize", str(raw_id)),
    ).scalar_one_or_none()
    if prior:
        return prior
    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "series.normalize",
        "handler_version": VERSION,
        "source_id": job["source_id"],
        "business_code": job["business_code"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_attempts": 1,
        "max_external_calls": 0,
        "idempotency_key": str(raw_id),
    }
    handler = NormalizeSeries()
    frozen = handler.freeze(c, values, az, raw_id=raw_id)
    create_task(
        c,
        {**values, "input_sha256": input_digest(values, frozen)},
        [{"role": "material", "raw_asset_id": raw_id}],
    )
    return tid
