"""Explicit local saved-HTML import; no connector, HTTP call or background dispatch."""

import hashlib
from uuid import UUID

from app.collection.handler import publish_batch
from app.collection.novels import submit
from app.collection.service import get, insert
from app.connectors.novels import VERSION
from app.connectors.qidian_desktop import METHOD, discover, normalize
from app.intelligence.service import shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org
from app.tasks.service import Runner, TaskError


class SavedQidian:
    action = "collection.run"

    def freeze(self, c, task, az):
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .one()
        )
        board = job["safe_request"]
        source = az.require("sources", job["source_id"], self.action)
        raw = az.read("raw_assets", UUID(board["raw_asset_id"]))
        conn = get(c, "provider_connections", task["org_id"], job["connection_id"])
        if (
            board.get("method") != METHOD
            or board.get("platform") != "qidian"
            or board.get("gender") != "female"
            or board.get("capture_kind") != "user_saved_html"
            or board.get("code") != f"qidian:desktop:female:{board.get('rank_type')}"
            or source["platform_code"] != "qidian"
            or source["board_code"] != board["code"]
            or source["business_code"] != task["business_code"]
            or not source["enabled"]
            or source["target_kind"] != "board"
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "novel_public"
            or conn["secret_ref"] != "PUBLIC_NOVEL_NO_SECRET"
            or task["max_external_calls"] != 0
            or job["plan_id"] is not None
            or job["connector_version"] != VERSION
            or job["capability_code"] != "novel.qidian.board"
            or job["max_requests"] != 1
            or job["max_items"] != 30
            or digest(board) != job["request_sha256"]
            or raw["origin"] != "manual"
            or raw["submitted_by"] != task["requested_by"]
            or raw["sha256"] != board["file_sha256"]
            or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
            or shanghai_date(raw["captured_at"]) != job["business_date"]
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "source_version": source["lock_version"],
            "connection_version": conn["lock_version"],
            "request": board,
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
        raw = get(c, "raw_assets", task["org_id"], UUID(result["raw_asset_id"]))
        if result["raw_asset_id"] != job["safe_request"]["raw_asset_id"]:
            raise TaskError("INVALID_INPUT")
        batch = normalize(job["safe_request"], raw["body_text"])
        publish_batch(c, task, raw, job, batch)
        audit(
            c,
            task["org_id"],
            task["requested_by"],
            "novel.saved_html_imported",
            "raw_asset",
            raw["id"],
        )


def run_saved(engine, org, task_id):
    outcome = Runner(engine, {("collect.novels", VERSION): SavedQidian()}).run(org, task_id)
    with engine.begin() as c:
        state = c.exec_driver_sql(
            "SELECT state FROM tasks WHERE org_id=%s AND id=%s", (org, task_id)
        ).scalar_one()
    return {"run_outcome": outcome, "task_state": state}


def submit_saved(c, p, board, html, *, business="motion_comic"):
    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    for action in ("source.configure", "collection.run", "evidence.read"):
        if not az.allowed(action, {("org", str(p.org_id)), ("business", business)}):
            raise TaskError("ACCESS_DENIED")
    # Only a real catalog-discovered board may be imported; normalization happens in the task.
    if board not in discover(html):
        raise TaskError("INVALID_INPUT")
    sha = hashlib.sha256(html.encode()).hexdigest()
    old = (
        c.exec_driver_sql(
            "SELECT j.task_id,j.id job_id,j.source_id,j.safe_request FROM collection_jobs j JOIN sources s ON s.org_id=j.org_id AND s.id=j.source_id WHERE j.org_id=%s AND j.business_code=%s AND j.business_date=%s AND s.board_code=%s ORDER BY j.created_at DESC LIMIT 1",
            (p.org_id, business, shanghai_date(), board["code"]),
        )
        .mappings()
        .one_or_none()
    )
    if old:
        if old["safe_request"].get("file_sha256") != sha:
            raise TaskError("IDEMPOTENCY_CONFLICT")
        return {k: str(old[k]) for k in ("task_id", "job_id", "source_id")}
    now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
    raw_id = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="manual",
        asset_kind="response",
        submitted_by=p.member_id,
        body_text=html,
        sha256=sha,
        captured_at=now,
    )
    request = {
        **board,
        "capture_kind": "user_saved_html",
        "file_sha256": sha,
        "raw_asset_id": str(raw_id),
        "imported_at": now.isoformat(),
        "source_captured_at": None,
    }
    return submit(
        c,
        p,
        request,
        SavedQidian(),
        business=business,
        external_calls=0,
        inputs=({"role": "novel_saved_html", "raw_asset_id": raw_id},),
    )
