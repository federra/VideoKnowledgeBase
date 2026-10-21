"""Offline recovery of received evidence after the TEXT/NUL storage failure; never retries HTTP."""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.collection.handler import publish_batch
from app.collection.service import get, insert
from app.connectors.hongguo import HOST, VERSION, encode_html, normalize_board
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.sessions import refresh
from app.security.storage import audit
from app.tasks.service import TaskError, input_digest


class RecoverBoard:
    action = "collection.run"

    def freeze(self, c, task, az, *, raw_id=None):
        if raw_id is None:
            raw_id = c.exec_driver_sql(
                "SELECT raw_asset_id FROM task_inputs WHERE org_id=%s AND task_id=%s",
                (task["org_id"], task["id"]),
            ).scalar_one()
        raw = az.read("raw_assets", raw_id)
        job = row(c, "collection_jobs", task["org_id"], raw["collection_job_id"])
        source = az.require("sources", job["source_id"], self.action)
        call = row(c, "collection_calls", task["org_id"], raw["collection_call_id"])
        if (
            job["capability_code"] != "hongguo.board"
            or job["connector_version"] != VERSION
            or source["platform_code"] != "hongguo"
            or source["id"] != task["source_id"]
            or call["http_status"] != 200
            or call["outcome"] not in ("success", "invalid_shape")
            or call["job_id"] != job["id"]
            or job["business_date"] != shanghai_date(raw["captured_at"])
            or task["max_external_calls"] != 0
            or task["business_code"] != job["business_code"]
        ):
            raise TaskError("INVALID_INPUT")
        normalize_board(raw["body_text"], job["safe_request"]["board"])
        return {"raw_id": str(raw_id), "sha256": raw["sha256"]}

    def execute(self, payload, checkpoint):
        checkpoint()
        return payload

    def publish(self, c, task, result):
        raw = get(c, "raw_assets", task["org_id"], UUID(result["raw_id"]))
        job = get(c, "collection_jobs", task["org_id"], raw["collection_job_id"])
        snap = publish_batch(
            c,
            task,
            raw,
            job,
            normalize_board(raw["body_text"], job["safe_request"]["board"]),
            record_output=False,
        )
        manifest = json.dumps({"source_raw_id": str(raw["id"]), "snapshot_id": str(snap)})
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
            captured_at=raw["captured_at"],
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"],
                task_id=task["id"],
                position=0,
                role="hongguo_offline_recovery",
                raw_asset_id=derived,
            )
        )


def retain_and_submit(c, p, job_id, filename):
    refresh(c, p)
    job = row(c, "collection_jobs", p.org_id, job_id)
    az = Authorizer(c, p)
    az.require("sources", job["source_id"], "collection.run")
    if job["capability_code"] != "hongguo.board" or job["connector_version"] != VERSION:
        raise TaskError("INVALID_INPUT")
    capture = json.loads(filename.with_suffix(".json").read_text())
    raw_html = filename.read_bytes().decode("utf-8")
    captured_at = datetime.fromisoformat(capture["captured_at"])
    # The local VM database clock can lead the host by milliseconds. New captures
    # also bind the exact job ID; allow a bounded skew only with that binding.
    bound_job = capture.get("collection_job_id")
    if bound_job is not None and bound_job != str(job_id):
        raise TaskError("INVALID_INPUT")
    skew = timedelta(seconds=2 if bound_job else 0)
    call = (
        c.exec_driver_sql(
            "SELECT cc.*,a.started_at,a.finished_at FROM collection_calls cc JOIN task_attempts a ON a.id=cc.attempt_id AND a.org_id=cc.org_id WHERE cc.org_id=%s AND cc.job_id=%s",
            (p.org_id, job_id),
        )
        .mappings()
        .one()
    )
    if (
        capture["url"] != HOST + "/rank/" + job["safe_request"]["board"]
        or capture["http_status"] != 200
        or hashlib.sha256(raw_html.encode()).hexdigest() != capture["sha256"]
        or captured_at < call["reserved_at"] - skew
        or captured_at < call["started_at"] - skew
        or not call["finished_at"]
        or captured_at > call["finished_at"] + skew
        or shanghai_date(captured_at) != job["business_date"]
    ):
        raise TaskError("INVALID_INPUT")
    batch = normalize_board(raw_html, job["safe_request"]["board"])
    body = encode_html(raw_html)
    old = c.exec_driver_sql(
        "SELECT id FROM raw_assets WHERE org_id=%s AND collection_call_id=%s",
        (p.org_id, call["id"]),
    ).scalar_one_or_none()
    if old:
        raw_id = old
        retained = row(c, "raw_assets", p.org_id, raw_id)
        if (
            retained["body_text"] != body
            or retained["sha256"] != hashlib.sha256(body.encode()).hexdigest()
        ):
            raise TaskError("INVALID_INPUT")
    else:
        if call["outcome"] is not None:
            raise TaskError("INVALID_INPUT")
        c.execute(
            metadata.tables["collection_calls"]
            .update()
            .where(metadata.tables["collection_calls"].c.id == call["id"])
            .values(
                completed_at=captured_at,
                http_status=200,
                outcome="success",
                returned_items=batch.returned_items,
            )
        )
        raw_id = insert(
            c,
            "raw_assets",
            p.org_id,
            origin="api",
            asset_kind="response",
            collection_job_id=job_id,
            collection_call_id=call["id"],
            body_text=body,
            sha256=hashlib.sha256(body.encode()).hexdigest(),
            captured_at=captured_at,
        )
        audit(c, p.org_id, p.member_id, "hongguo.response_retained_offline", "raw_asset", raw_id)
    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "hongguo.recover",
        "handler_version": VERSION,
        "source_id": job["source_id"],
        "business_code": job["business_code"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_external_calls": 0,
        "max_attempts": 1,
        "idempotency_key": str(raw_id) + ":nul-projection-v2",
    }
    handler = RecoverBoard()
    values["input_sha256"] = input_digest(values, handler.freeze(c, values, az, raw_id=raw_id))
    tid, _ = create_task(c, values, [{"role": "captured_response", "raw_asset_id": raw_id}])
    return tid
