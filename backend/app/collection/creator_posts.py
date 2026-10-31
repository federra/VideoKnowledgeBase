"""Audited, complete ordinary-video window; no comment-body or paid requests."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import func

from app.collection.handler import publish_batch
from app.collection.service import get, insert
from app.connectors import douyin_posts as dp
from app.core.models import metadata
from app.intelligence.creators import active
from app.intelligence.service import shanghai_date
from app.security.primitives import digest
from app.tasks.service import TaskError


def saved_pages(c, org, job, az=None):
    raws = (
        c.exec_driver_sql(
            "SELECT r.*,cc.sequence_no,cc.outcome FROM raw_assets r JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id WHERE r.org_id=%s AND r.collection_job_id=%s ORDER BY cc.sequence_no",
            (org, job["id"]),
        )
        .mappings()
        .all()
    )
    if any(
        raw["sequence_no"] != index or raw["outcome"] != "success"
        for index, raw in enumerate(raws, 1)
    ):
        raise TaskError("INVALID_RESPONSE")
    from app.collection.page_resume import reuse_rows

    raws = list(reuse_rows(c, org, job, az)) + list(raws)
    pages, assets, cursor = [], {}, 0
    for raw in raws:
        if raw["outcome"] != "success":
            raise TaskError("INVALID_RESPONSE")
        if az:
            az.read("raw_assets", raw["id"])
        body = json.loads(raw["body_text"])
        for r in dp.normalize_page(
            body, job["safe_request"]["sec_user_id"], job["safe_request"]["uid"]
        ).records:
            assets.setdefault(r["platform_content_id"], raw)
        pages.append((cursor, body))
        cursor = body["max_cursor"]
    return raws, pages, assets


class CreatorPosts:
    action = "collection.run"

    def __init__(self, connector, parent_checkpoint=None):
        self.connector, self.parent_checkpoint = connector, parent_checkpoint

    def freeze(self, c, task, az):
        org = task["org_id"]
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, task["id"])
            )
            .mappings()
            .one()
        )
        src = az.require("sources", job["source_id"], self.action)
        conn = get(c, "provider_connections", org, job["connection_id"])
        req = job["safe_request"]
        entry = req.get("entry") or {}
        account = get(c, "external_accounts", org, src["account_id"])
        _, end = dp.bounds(req.get("window"))
        if (
            not src["enabled"]
            or src["platform_code"] != "douyin"
            or src["target_kind"] != "account"
            or task["business_code"] != "story_short"
            or src["business_code"] != task["business_code"]
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "douyin_session"
            or conn["secret_ref"] != "LOCAL_DOUYIN_BROWSER_SESSION"
            or job["capability_code"] != dp.CAPABILITY
            or job["connector_version"] != dp.VERSION
            or job["plan_id"] is not None
            or job["max_requests"] != dp.MAX_PAGES
            or job["max_items"] != dp.MAX_ITEMS
            or task["max_external_calls"] != dp.MAX_PAGES
            or task["max_attempts"] != 1
            or digest(req) != job["request_sha256"]
            or req.get("policy") != dp.POLICY
            or req.get("uid") != account["platform_uid"]
            or end.date() != job["business_date"]
            or entry.get("url") != "https://www.douyin.com/user/" + req.get("sec_user_id", "")
        ):
            raise TaskError("INVALID_INPUT")
        if not active(c, org, "story_short", entry):
            raise TaskError("ACCESS_REVOKED")
        evidence = UUID(req["identity_evidence"])
        az.read("raw_assets", evidence)
        if not c.exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM external_account_aliases WHERE org_id=%s AND account_id=%s AND alias_kind='sec_uid' AND alias_value=%s AND raw_asset_id=%s)",
            (org, account["id"], req["sec_user_id"], evidence),
        ).scalar_one():
            raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "source_version": src["lock_version"],
            "connection_version": conn["lock_version"],
            "request": req,
            "day": str(job["business_date"]),
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        req = ticket.payload["request"]
        job_id = UUID(ticket.payload["job_id"])

        def fence():
            if self.parent_checkpoint:
                self.parent_checkpoint()
            checkpoint()
            if str(shanghai_date()) != ticket.payload["day"]:
                raise TaskError("DATE_WINDOW_MISMATCH")

        self.connector.before_request = fence
        pages, cursor = [], 0
        reused = ticket.payload.get("reused_pages", [])
        for saved in reused:
            body = saved["value"]
            pages.append((cursor, body))
            cursor = body["max_cursor"]
        if pages and dp.complete(pages[-1][1], req["window"]):
            raise TaskError("INVALID_INPUT")
        for sequence in range(1, dp.MAX_PAGES - len(reused) + 1):
            fence()
            with runner.engine.begin() as c:
                task = runner.live(c, ticket)
                if not task:
                    raise TaskError("ACCESS_REVOKED")
                runner.validate(c, task)
                call = insert(
                    c,
                    "collection_calls",
                    ticket.org,
                    job_id=job_id,
                    attempt_id=ticket.attempt,
                    sequence_no=sequence,
                    request_sha256=digest(
                        {"sec_user_id": req["sec_user_id"], "max_cursor": cursor}
                    ),
                )
            reply = self.connector.fetch(req["sec_user_id"], cursor)
            with runner.engine.begin() as c:
                c.execute(
                    metadata.tables["collection_calls"]
                    .update()
                    .where(metadata.tables["collection_calls"].c.id == call)
                    .values(
                        completed_at=func.clock_timestamp(),
                        http_status=reply.http_status,
                        outcome=reply.outcome,
                    )
                )
                insert(
                    c,
                    "raw_assets",
                    ticket.org,
                    origin="api",
                    asset_kind="response",
                    collection_job_id=job_id,
                    collection_call_id=call,
                    body_text=reply.raw_text,
                    sha256=hashlib.sha256(reply.raw_text.encode()).hexdigest(),
                    captured_at=reply.captured_at,
                )
            if reply.error:
                raise TaskError(reply.error)
            body = json.loads(reply.raw_text)
            dp.normalize_page(body, req["sec_user_id"], req["uid"])
            pages.append((cursor, body))
            if dp.complete(body, req["window"]):
                break
            next_cursor = body["max_cursor"]
            if next_cursor == 0 or (cursor and next_cursor >= cursor):
                raise TaskError("INVALID_RESPONSE")
            cursor = next_cursor
        batch = dp.combine(pages, req["sec_user_id"], req["uid"], req["window"])
        fence()
        return {"business_outcome": "completed", "items": len(batch.records)}

    def publish(self, c, task, result):
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .one()
        )
        raws, pages, assets = saved_pages(c, task["org_id"], job)
        if any(shanghai_date(r["captured_at"]) != job["business_date"] for r in raws):
            raise TaskError("DATE_WINDOW_MISMATCH")
        req = job["safe_request"]
        batch = dp.combine(pages, req["sec_user_id"], req["uid"], req["window"])
        publish_batch(c, task, raws[0], job, batch, record_assets=assets)
