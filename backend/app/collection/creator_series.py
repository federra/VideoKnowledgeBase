"""Complete catalog before TOP10 publication; original JSON retained for every call."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import func

from app.collection.handler import publish_batch
from app.collection.service import get, insert
from app.connectors.douyin_series import (
    CAPABILITY,
    MAX_CALLS,
    MAX_PAGES,
    POLICY,
    VERSION,
    catalog,
    comments,
    first_episode,
    top,
)
from app.connectors.redfox import AdapterError
from app.core.models import metadata
from app.intelligence.creators import active
from app.intelligence.service import shanghai_date
from app.security.primitives import digest
from app.tasks.service import TaskError


class CreatorSeries:
    action = "collection.run"

    def __init__(self, connector, parent_checkpoint=None):
        self.connector = connector
        self.parent_checkpoint = parent_checkpoint

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
        request = job["safe_request"]
        entry = request.get("entry") or {}
        account = get(c, "external_accounts", org, src["account_id"])
        if (
            not src["enabled"]
            or src["platform_code"] != "douyin"
            or src["target_kind"] != "account"
            or src["business_code"] != task["business_code"]
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "douyin_public"
            or conn["secret_ref"] != "PUBLIC_DOUYIN_NO_SECRET"
            or job["capability_code"] != CAPABILITY
            or job["connector_version"] != VERSION
            or job["plan_id"] is not None
            or job["max_requests"] != MAX_CALLS
            or job["max_items"] != 10
            or task["max_external_calls"] != MAX_CALLS
            or task["max_attempts"] != 1
            or digest(request) != job["request_sha256"]
            or request.get("policy") != POLICY
            or request.get("uid") != account["platform_uid"]
            or entry.get("url") != "https://www.douyin.com/user/" + request.get("sec_user_id", "")
        ):
            raise TaskError("INVALID_INPUT")
        if not active(c, org, task["business_code"], entry):
            raise TaskError("ACCESS_REVOKED")
        deps = (
            c.exec_driver_sql(
                "SELECT raw_asset_id FROM task_inputs WHERE org_id=%s AND task_id=%s",
                (org, task["id"]),
            )
            .scalars()
            .all()
        )
        # At submit time inputs are passed explicitly, before create_task inserts them.
        evidence = request.get("identity_evidence")
        if deps and deps != [UUID(evidence)]:
            raise TaskError("INVALID_INPUT")
        az.read("raw_assets", UUID(evidence))
        alias = c.exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM external_account_aliases WHERE org_id=%s AND account_id=%s AND alias_kind='sec_uid' AND alias_value=%s AND raw_asset_id=%s)",
            (org, account["id"], request["sec_user_id"], UUID(evidence)),
        ).scalar_one()
        if not alias:
            raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "source_version": src["lock_version"],
            "connection_version": conn["lock_version"],
            "request": request,
            "day": str(job["business_date"]),
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        job_id = UUID(ticket.payload["job_id"])
        req = ticket.payload["request"]
        sec, uid = req["sec_user_id"], req["uid"]

        def fence():
            if self.parent_checkpoint:
                self.parent_checkpoint()
            checkpoint()
            if str(shanghai_date()) != ticket.payload["day"]:
                raise TaskError("DATE_WINDOW_MISMATCH")

        self.connector.before_request = fence

        def request(kind, target, cursor=0):
            if self.parent_checkpoint:
                self.parent_checkpoint()
            checkpoint()
            with runner.engine.begin() as c:
                task = runner.live(c, ticket)
                if not task:
                    raise TaskError("ACCESS_REVOKED")
                runner.validate(c, task)
                if str(shanghai_date()) != ticket.payload["day"]:
                    raise TaskError("DATE_WINDOW_MISMATCH")
                sequence = c.exec_driver_sql(
                    "SELECT count(*)+1 FROM collection_calls WHERE org_id=%s AND job_id=%s",
                    (ticket.org, job_id),
                ).scalar_one()
                call = insert(
                    c,
                    "collection_calls",
                    ticket.org,
                    job_id=job_id,
                    attempt_id=ticket.attempt,
                    sequence_no=sequence,
                    request_sha256=digest({"kind": kind, "target": target, "cursor": cursor}),
                )
            try:
                reply = self.connector.fetch(kind, target, cursor)
            except (AdapterError, TaskError) as exc:
                # Known local cooldown: no network attempt; preserve a completed failed receipt.
                from datetime import UTC, datetime

                from app.connectors.redfox import Reply

                reply = Reply(
                    None,
                    None,
                    "invalid_shape",
                    "[public source unavailable before request]",
                    datetime.now(UTC),
                    error=exc.code if isinstance(exc, TaskError) else str(exc),
                )
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
                raw = insert(
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
            checkpoint()
            return raw, json.loads(reply.raw_text)

        pages, assets, cursor, seen = [], {}, 0, set()
        for _ in range(MAX_PAGES):
            if cursor in seen:
                raise TaskError("INVALID_RESPONSE")
            seen.add(cursor)
            raw, body = request("catalog", sec, cursor)
            for r in catalog(body, sec, uid):
                assets.setdefault("series:" + r["series_id"], str(raw))
            pages.append((cursor, body))
            if body["has_more"] == 0:
                break
            cursor = body["cursor"]
        batch = top(pages, sec, uid)
        samples, unavailable = [], []
        for index, record in enumerate(batch.records):
            sid = record["platform_content_id"].split(":", 1)[1]
            try:
                episode_raw, body = request("episodes", sid)
                aid = first_episode(body, sid, uid)
                raw, body = request("comments", aid)
                comments(body, aid)
            except (TaskError, AdapterError) as exc:
                code = exc.code if isinstance(exc, TaskError) else str(exc)
                if code not in ("INVALID_RESPONSE", "SOURCE_UNAVAILABLE"):
                    raise
                unavailable = [
                    r["platform_content_id"].split(":", 1)[1] for r in batch.records[index:]
                ]
                break  # Directory TOP remains valid; do not burst against blocked detail/comments.
            samples.append(
                {
                    "series_id": sid,
                    "aweme_id": aid,
                    "episode_raw": str(episode_raw),
                    "raw": str(raw),
                }
            )
        if self.parent_checkpoint:
            self.parent_checkpoint()
        return {
            "catalog_raws": [str(v) for v in dict.fromkeys(assets.values())],
            "assets": assets,
            "samples": samples,
            "unavailable": unavailable,
            "business_outcome": "insufficient_evidence" if unavailable else "completed",
        }

    def publish(self, c, task, result, *, original_job=None):
        org = task["org_id"]
        job = original_job or (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, task["id"])
            )
            .mappings()
            .one()
        )
        req = job["safe_request"]
        # Reconstruct all catalog pages from persisted request order, including empty pages.
        raws = (
            c.exec_driver_sql(
                "SELECT r.* FROM raw_assets r JOIN collection_calls cc ON cc.id=r.collection_call_id AND cc.org_id=r.org_id WHERE r.org_id=%s AND r.collection_job_id=%s ORDER BY cc.sequence_no",
                (org, job["id"]),
            )
            .mappings()
            .all()
        )
        pages, assets, rawmap, cursor = [], {}, {}, 0
        for raw in raws:
            if shanghai_date(raw["captured_at"]) != job["business_date"]:
                raise TaskError("DATE_WINDOW_MISMATCH")
            rawmap[str(raw["id"])] = raw
            try:
                body = json.loads(raw["body_text"])
            except ValueError:
                continue
            if isinstance(body, dict) and "series_infos" in body:
                pages.append((cursor, body))
                for s in catalog(body, req["sec_user_id"], req["uid"]):
                    assets.setdefault("series:" + s["series_id"], raw)
                cursor = body["cursor"]
        batch = top(pages, req["sec_user_id"], req["uid"])
        selected = {r["platform_content_id"].split(":", 1)[1] for r in batch.records}
        available = [v["series_id"] for v in result["samples"]]
        unavailable = result.get("unavailable", [])
        if (
            len(set(available + unavailable)) != len(available + unavailable)
            or set(available + unavailable) != selected
        ):
            raise TaskError("INVALID_RESPONSE")
        snapshot = publish_batch(
            c, task, raws[0], job, batch, record_assets=assets, record_output=original_job is None
        )
        wanted = {r["platform_content_id"].split(":", 1)[1] for r in batch.records}
        for sample in result["samples"]:
            sid = sample["series_id"]
            if sid not in wanted:
                raise TaskError("INVALID_RESPONSE")
            wanted.remove(sid)
            ep, raw = rawmap[sample["episode_raw"]], rawmap[sample["raw"]]
            aid = first_episode(json.loads(ep["body_text"]), sid, req["uid"])
            if aid != sample["aweme_id"]:
                raise TaskError("INVALID_RESPONSE")
            content = c.exec_driver_sql(
                "SELECT id FROM external_contents WHERE org_id=%s AND platform_code='douyin' AND platform_content_id=%s",
                (org, "series:" + sid),
            ).scalar_one()
            for value in comments(json.loads(raw["body_text"]), aid):
                insert(
                    c,
                    "comment_evidence",
                    org,
                    content_id=content,
                    raw_asset_id=raw["id"],
                    captured_at=raw["captured_at"],
                    **value,
                )
        from app.security.storage import audit

        audit(
            c,
            org,
            task["requested_by"],
            "creator.series.captured",
            "intelligence_snapshot",
            snapshot,
        )
        manifest = json.dumps(
            {"snapshot": str(snapshot), "samples": result["samples"], "unavailable": unavailable},
            sort_keys=True,
        )
        raw_id = insert(
            c,
            "raw_assets",
            org,
            origin="processing",
            asset_kind="response",
            processing_task_id=task["id"],
            parent_raw_asset_id=UUID(req["identity_evidence"]),
            body_text=manifest,
            sha256=hashlib.sha256(manifest.encode()).hexdigest(),
            captured_at=func.clock_timestamp(),
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=org,
                task_id=task["id"],
                position=1 if original_job is None else 0,
                role="creator_series_manifest",
                raw_asset_id=raw_id,
            )
        )
