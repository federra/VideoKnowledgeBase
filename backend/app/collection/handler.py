"""Reserve before network; retain evidence independently; publish only under task fence."""

import json
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.collection.service import get, identity, insert
from app.connectors.redfox import VERSION, AdapterError, evidence_sha, item_limit, normalize
from app.core.models import metadata
from app.security.primitives import digest
from app.tasks.service import TaskError


class Collect:
    action = "collection.run"

    def __init__(self, connector, *, min_interval=2):
        self.connector, self.min_interval = connector, min_interval

    def freeze(self, c, task, az):
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .one()
        )
        source = az.require("sources", job["source_id"], self.action)
        conn = get(c, "provider_connections", task["org_id"], job["connection_id"])
        if (
            not source["enabled"]
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "redfox"
            or conn["secret_ref"] != "REDFOX_API_KEY"
            or job["connector_version"] != VERSION
            or digest(job["safe_request"]) != job["request_sha256"]
            or job["max_requests"] != 1
            or not 1 <= job["max_items"] <= item_limit(job["capability_code"])
            or task["max_external_calls"] != 1
        ):
            raise TaskError("INVALID_INPUT")
        plan = (
            get(c, "collection_plans", task["org_id"], job["plan_id"]) if job["plan_id"] else None
        )
        if plan and (
            not plan["enabled"]
            or plan["connector_version"] != VERSION
            or plan["schedule_timezone"] != "Asia/Shanghai"
            or plan["authorized_by"] != task["execution_authorized_by"]
        ):
            raise TaskError("INVALID_INPUT")
        if (
            plan
            and plan["request_options"].get("purpose") in ("knowledge", "both")
            and not az.allowed("knowledge.edit", az.scopes("sources", source))
        ):
            from app.security.errors import Denied

            raise Denied("ACCESS_DENIED")
        frozen = {
            "job_id": str(job["id"]),
            "source_version": source["lock_version"],
            "connection_version": conn["lock_version"],
            "request": job["safe_request"],
            "capability": job["capability_code"],
            "maximum": job["max_items"],
            "business_date": str(job["business_date"]),
        }
        if plan:
            frozen.update(
                plan_version=plan["lock_version"],
                purpose=plan["request_options"].get("purpose", "intelligence"),
            )
        return frozen

    def defer(self, c, task):
        """Connection contention is queued work, not a failed provider attempt."""
        from datetime import timedelta

        from app.core.repository import compare_and_swap

        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .one()
        )
        busy = c.exec_driver_sql(
            "SELECT EXISTS (SELECT 1 FROM collection_jobs j JOIN tasks t ON t.id=j.task_id "
            "JOIN task_attempts a ON a.task_id=t.id WHERE j.org_id=%s AND j.connection_id=%s "
            "AND t.id<>%s AND t.state IN ('running','cancel_requested') AND a.finished_at IS NULL "
            "AND a.lease_expires_at>clock_timestamp() AND (%s OR j.plan_id IS NOT NULL))",
            (task["org_id"], job["connection_id"], task["id"], job["plan_id"] is not None),
        ).scalar_one()
        if not job["plan_id"] and not busy:
            return False
        recent = c.exec_driver_sql(
            "SELECT EXISTS (SELECT 1 FROM collection_calls cc JOIN collection_jobs j ON j.id=cc.job_id "
            "WHERE j.org_id=%s AND j.connection_id=%s AND cc.reserved_at>clock_timestamp()-(%s * interval '1 second'))",
            (task["org_id"], job["connection_id"], self.min_interval),
        ).scalar_one()
        if not busy and not recent:
            return False
        now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
        compare_and_swap(
            c,
            "tasks",
            task["org_id"],
            task["id"],
            task["lock_version"],
            {"available_at": now + timedelta(seconds=max(10, self.min_interval))},
        )
        return True

    def execute_ticket(self, runner, ticket, checkpoint):
        try:
            self.connector.ready()
        except AdapterError as e:
            raise TaskError(str(e)) from None
        with runner.engine.begin() as c:
            task = runner.live(c, ticket)
            if not task:
                raise TaskError("ACCESS_REVOKED")
            runner.validate(c, task)
            job = get(c, "collection_jobs", ticket.org, UUID(ticket.payload["job_id"]))
            recent = c.exec_driver_sql(
                "SELECT EXISTS (SELECT 1 FROM collection_calls cc JOIN collection_jobs j ON j.id=cc.job_id WHERE j.org_id=%s AND j.connection_id=%s AND cc.reserved_at > clock_timestamp()-(%s * interval '1 second'))",
                (ticket.org, job["connection_id"], self.min_interval),
            ).scalar_one()
            if recent:
                raise TaskError("RATE_LIMITED")
            call_id = insert(
                c,
                "collection_calls",
                ticket.org,
                job_id=job["id"],
                attempt_id=ticket.attempt,
                sequence_no=1,
                request_sha256=job["request_sha256"],
            )
        reply = self.connector.fetch(
            job["capability_code"], job["safe_request"], maximum=job["max_items"]
        )
        with runner.engine.begin() as c:
            # Current permission/lease may be gone: these are external facts, not task products.
            from app.security.storage import lock_org

            lock_org(c, ticket.org)
            c.execute(
                metadata.tables["collection_calls"]
                .update()
                .where(metadata.tables["collection_calls"].c.id == call_id)
                .values(
                    completed_at=func.clock_timestamp(),
                    http_status=reply.http_status,
                    provider_code=str(reply.provider_code)
                    if reply.provider_code is not None
                    else None,
                    outcome=reply.outcome,
                    returned_items=reply.batch.returned_items if reply.batch else None,
                )
            )
            raw = insert(
                c,
                "raw_assets",
                ticket.org,
                origin="api",
                asset_kind="response",
                collection_job_id=job["id"],
                collection_call_id=call_id,
                body_text=reply.raw_text,
                sha256=evidence_sha(reply),
                captured_at=reply.captured_at,
            )
        if reply.error:
            raise TaskError(reply.error)
        checkpoint()
        return {"raw_asset_id": str(raw), "call_id": str(call_id)}

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
        ):
            raise TaskError("INVALID_INPUT")
        if raw["captured_at"].astimezone(ZoneInfo("Asia/Shanghai")).date() != job["business_date"]:
            raise TaskError("DATE_WINDOW_MISMATCH")
        try:
            batch = normalize(
                job["capability_code"],
                json.loads(raw["body_text"]),
                maximum=job["max_items"],
                target=job["safe_request"].get("userId"),
            )
        except (AdapterError, ValueError):
            raise TaskError("INVALID_RESPONSE") from None
        publish_batch(c, task, raw, job, batch)


def publish_batch(c, task, raw, job, batch, *, record_output=True):
    """Persist an already authorized batch; no external I/O."""
    org = task["org_id"]
    platform = get(c, "sources", org, job["source_id"])["platform_code"]
    version = c.exec_driver_sql(
        "SELECT coalesce(max(version_no),0)+1 FROM intelligence_snapshots WHERE org_id=%s AND source_id=%s AND business_date=%s AND view_kind=%s",
        (org, job["source_id"], job["business_date"], batch.view_kind),
    ).scalar_one()
    snap = insert(
        c,
        "intelligence_snapshots",
        org,
        source_id=job["source_id"],
        job_id=job["id"],
        business_code=job["business_code"],
        business_date=job["business_date"],
        view_kind=batch.view_kind,
        version_no=version,
        entry_count=len(batch.records),
    )
    aliases_seen = set()
    for position, record in enumerate(batch.records):
        account = None
        if record.get("platform_uid"):
            account = identity(
                c,
                "external_accounts",
                org,
                "platform_uid",
                record["platform_uid"],
                display_name=record["account_display_name"],
                platform=platform,
            )
            for kind, value in record["aliases"]:
                alias_key = (account, kind, value)
                if alias_key in aliases_seen:
                    continue
                aliases_seen.add(alias_key)
                insert(
                    c,
                    "external_account_aliases",
                    org,
                    account_id=account,
                    alias_kind=kind,
                    alias_value=value,
                    raw_asset_id=raw["id"],
                    observed_at=raw["captured_at"],
                )
        if batch.view_kind == "account_discovery":
            obs = insert(
                c,
                "account_observations",
                org,
                account_id=account,
                raw_asset_id=raw["id"],
                observed_at=raw["captured_at"],
                **record["account"],
            )
            field = "account_observation_id"
        else:
            content = identity(
                c,
                "external_contents",
                org,
                "platform_content_id",
                record["platform_content_id"],
                account_id=account,
                platform=platform,
            )
            obs = insert(
                c,
                "content_observations",
                org,
                content_id=content,
                raw_asset_id=raw["id"],
                observed_at=raw["captured_at"],
                **record["content"],
            )
            field = "content_observation_id"
        insert(
            c,
            "snapshot_entries",
            org,
            snapshot_id=snap,
            position=position,
            provider_rank=record.get("provider_rank"),
            **{field: obs},
        )
    c.exec_driver_sql("SELECT cip_seal('intelligence_snapshots',%s,%s)", (org, snap))
    if record_output:
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=org,
                task_id=task["id"],
                position=0,
                role="collection_snapshot",
                snapshot_id=snap,
            )
        )

    # Downstream handoff freezes the identical response; it never makes another provider call.
    if job["plan_id"]:
        from app.collection.schedule import handoff

        handoff(c, task, raw)

    return snap
