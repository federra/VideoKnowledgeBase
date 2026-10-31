"""Explicit import of an authorized, complete public HTTP capture; never performs I/O."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.collection.handler import publish_batch
from app.collection.service import get, insert
from app.connectors.hongguo import BOARDS, HOST, VERSION, normalize_board, response_html
from app.connectors.redfox import AdapterError
from app.core.repository import compare_and_swap, create_task
from app.intelligence.service import shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org
from app.tasks.service import Runner, TaskError, input_digest

METHOD = "hongguo-saved-http-v1"
KIND = "collect.hongguo.saved"
CAPTURE = "authorized_http_capture"
INPUT_ROLE = "hongguo_saved_capture"
MAX_BODY = 4 * 1024 * 1024


def encode_saved(html, capture):
    body = html.encode("utf-8")
    return json.dumps(
        {
            "format": METHOD,
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "html_base64": base64.b64encode(body).decode("ascii"),
            "capture": capture,
        },
        ensure_ascii=False,
    )


def saved_html(body):
    try:
        if json.loads(body).get("format") != METHOD:
            raise TaskError("INVALID_INPUT")
        return response_html(body)
    except (ValueError, TypeError, AttributeError, AdapterError):
        raise TaskError("INVALID_INPUT") from None


def validate_capture(html, capture, board):
    """Keep acquisition time and SHA distinct from later manual import provenance."""
    try:
        body = html.encode("utf-8")
        sha = hashlib.sha256(body).hexdigest()
        captured = datetime.fromisoformat(capture["captured_at"])
        requested = datetime.fromisoformat(capture["requested_at"])
        if (
            board not in BOARDS
            or not body
            or len(body) > MAX_BODY
            or capture["url"] != HOST + "/rank/" + board
            or type(capture["http_status"]) is not int
            or capture["http_status"] != 200
            or capture["body_complete"] is not True
            or capture["text_available"] is not True
            or capture["sha256"] != sha
            or capture["body_sha256"] != sha
            or capture["body_representation"] != "httpx_decoded_bytes"
            or type(capture["saved_bytes"]) is not int
            or capture["saved_bytes"] != len(body)
            or type(capture["received_bytes"]) is not int
            or capture["received_bytes"] != len(body)
            or capture["content_type"] not in ("text/html", "application/xhtml+xml")
            or capture.get("collection_job_id") is not None
            or any(
                capture.get(k) is not None
                for k in ("failure_kind", "failure_stage", "exception_type")
            )
            or captured.tzinfo is None
            or requested.tzinfo is None
            or requested > captured
            or captured > datetime.now(UTC)
            or shanghai_date(captured) != shanghai_date()
            or normalize_board(html, board).returned_items not in range(1, 21)
        ):
            raise TaskError("INVALID_INPUT")
        return captured
    except (KeyError, TypeError, ValueError, AttributeError, AdapterError):
        raise TaskError("INVALID_INPUT") from None


def pause(c, p, source_id):
    source = Authorizer(c, p).require("sources", source_id, "source.configure")
    if source["enabled"]:
        compare_and_swap(
            c, "sources", p.org_id, source_id, source["lock_version"], {"enabled": False}
        )


class SavedHongguo:
    action = "collection.run"

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
        request = job["safe_request"]
        try:
            raw = az.read("raw_assets", UUID(request["raw_asset_id"]))
            envelope = json.loads(raw["body_text"])
            html, capture = saved_html(raw["body_text"]), envelope["capture"]
            captured = validate_capture(html, capture, request["board"])
            conn = get(c, "provider_connections", org, job["connection_id"])
            if (
                set(request) != {"method", "board", "raw_asset_id", "file_sha256", "capture_kind"}
                or request["method"] != METHOD
                or request["capture_kind"] != CAPTURE
                or task["kind"] != KIND
                or task["handler_version"] != VERSION
                or task["max_external_calls"] != 0
                or task["max_attempts"] != 1
                or job["capability_code"] != "hongguo.board"
                or job["connector_version"] != VERSION
                or job["plan_id"] is not None
                or job["max_requests"] != 1
                or job["max_items"] != 20
                or digest(request) != job["request_sha256"]
                or job["business_code"] != task["business_code"]
                or source["platform_code"] != "hongguo"
                or source["target_kind"] != "board"
                or source["board_code"] != request["board"]
                or source["id"] != task["source_id"]
                or source["business_code"] != task["business_code"]
                or not conn
                or not conn["enabled"]
                or conn["provider_code"] != "hongguo_public"
                or conn["secret_ref"] != "PUBLIC_HONGGUO_NO_SECRET"
                or raw["origin"] != "manual"
                or raw["asset_kind"] != "response"
                or raw["submitted_by"] != task["requested_by"]
                or raw["sha256"] != request["file_sha256"]
                or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
                or envelope["format"] != METHOD
                or envelope["response_sha256"] != capture["sha256"]
                or raw["captured_at"] != captured
                or shanghai_date(captured) != job["business_date"]
                or c.exec_driver_sql(
                    "SELECT EXISTS(SELECT 1 FROM collection_calls WHERE org_id=%s AND job_id=%s)",
                    (org, job["id"]),
                ).scalar_one()
                or (
                    task.get("inputs_sealed_at")
                    and c.exec_driver_sql(
                        "SELECT role,raw_asset_id FROM task_inputs WHERE org_id=%s AND task_id=%s ORDER BY position",
                        (org, task["id"]),
                    ).all()
                    != [(INPUT_ROLE, raw["id"])]
                )
            ):
                raise TaskError("INVALID_INPUT")
        except (KeyError, TypeError, ValueError, AttributeError):
            raise TaskError("INVALID_INPUT") from None
        return {
            "job_id": str(job["id"]),
            "source_version": source["lock_version"],
            "connection_version": conn["lock_version"],
            "request": request,
        }

    def execute(self, payload, checkpoint):
        checkpoint()
        return {"raw_asset_id": payload["request"]["raw_asset_id"]}

    def publish(self, c, task, result):
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .one()
        )
        if result != {"raw_asset_id": job["safe_request"]["raw_asset_id"]}:
            raise TaskError("INVALID_INPUT")
        raw = get(c, "raw_assets", task["org_id"], UUID(result["raw_asset_id"]))
        publish_batch(
            c, task, raw, job, normalize_board(raw["body_text"], job["safe_request"]["board"])
        )
        audit(
            c,
            task["org_id"],
            task["requested_by"],
            "hongguo.saved_http_imported",
            "raw_asset",
            raw["id"],
        )


def submit_saved(c, p, source_id, html, capture_metadata, key):
    try:
        source_id = UUID(str(source_id))
    except ValueError:
        raise TaskError("INVALID_INPUT") from None
    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    source = az.require("sources", source_id, "source.configure")
    az.require("sources", source_id, "collection.run")
    if not az.allowed("evidence.read", az.scopes("sources", source)):
        raise TaskError("ACCESS_DENIED")
    if source["platform_code"] != "hongguo" or source["target_kind"] != "board":
        raise TaskError("INVALID_INPUT")
    captured = validate_capture(html, capture_metadata, source["board_code"])
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise TaskError("INVALID_INPUT")
    body = encode_saved(html, capture_metadata)
    sha = hashlib.sha256(body.encode()).hexdigest()
    idem = digest({"source_id": str(source_id), "key": key, "member": str(p.member_id)})
    old = (
        c.exec_driver_sql(
            "SELECT t.id task_id,j.id job_id,j.source_id,j.safe_request FROM tasks t "
            "JOIN collection_jobs j ON j.org_id=t.org_id AND j.task_id=t.id "
            "WHERE t.org_id=%s AND t.kind=%s AND t.idempotency_key=%s",
            (p.org_id, KIND, idem),
        )
        .mappings()
        .one_or_none()
    )
    if old:
        if old["safe_request"]["file_sha256"] != sha or old["source_id"] != source_id:
            raise TaskError("IDEMPOTENCY_CONFLICT")
        pause(c, p, source_id)
        return {k: str(old[k]) for k in ("task_id", "job_id", "source_id")}
    conn = (
        c.exec_driver_sql(
            "SELECT * FROM provider_connections WHERE org_id=%s AND provider_code='hongguo_public' ORDER BY created_at,id LIMIT 1",
            (p.org_id,),
        )
        .mappings()
        .one_or_none()
    )
    if not conn or not conn["enabled"] or conn["secret_ref"] != "PUBLIC_HONGGUO_NO_SECRET":
        raise TaskError("SOURCE_UNAVAILABLE")
    # Offline parsing keeps the external source paused throughout.
    pause(c, p, source_id)
    raw_id = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="manual",
        asset_kind="response",
        submitted_by=p.member_id,
        body_text=body,
        sha256=sha,
        captured_at=captured,
    )
    request = {
        "method": METHOD,
        "board": source["board_code"],
        "raw_asset_id": str(raw_id),
        "file_sha256": sha,
        "capture_kind": CAPTURE,
    }
    task_id = uuid4()
    job_id = insert(
        c,
        "collection_jobs",
        p.org_id,
        task_id=task_id,
        source_id=source_id,
        connection_id=conn["id"],
        capability_code="hongguo.board",
        connector_version=VERSION,
        business_code=source["business_code"],
        business_date=shanghai_date(captured),
        safe_request=request,
        request_sha256=digest(request),
        max_requests=1,
        max_items=20,
    )
    task = {
        "id": task_id,
        "org_id": p.org_id,
        "kind": KIND,
        "handler_version": VERSION,
        "source_id": source_id,
        "business_code": source["business_code"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_external_calls": 0,
        "max_attempts": 1,
        "idempotency_key": idem,
    }
    task["input_sha256"] = input_digest(task, SavedHongguo().freeze(c, task, az))
    create_task(c, task, [{"role": INPUT_ROLE, "raw_asset_id": raw_id}])
    audit(c, p.org_id, p.member_id, "hongguo.saved_http_submitted", "task", task_id)
    return {"task_id": str(task_id), "job_id": str(job_id), "source_id": str(source_id)}


def run_saved(engine, p, task_id):
    task_id = UUID(str(task_id))
    source_id = None
    try:
        with engine.begin() as c:
            refresh(c, p)
            task = get(c, "tasks", p.org_id, task_id)
            if not task or task["kind"] != KIND or task["requested_by"] != p.member_id:
                raise TaskError("INVALID_INPUT")
            Authorizer(c, p).require("sources", task["source_id"], "collection.run")
            source_id = task["source_id"]
        outcome = Runner(engine, {(KIND, VERSION): SavedHongguo()}).run(p.org_id, task_id)
        with engine.begin() as c:
            state = get(c, "tasks", p.org_id, task_id)["state"]
        return {"run_outcome": outcome, "task_state": state}
    finally:
        if source_id is not None:
            with engine.begin() as c:
                refresh(c, p)
                lock_org(c, p.org_id)
                pause(c, p, source_id)
