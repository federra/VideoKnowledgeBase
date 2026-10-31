"""Explicit, fenced one-read homepage resolution, separate from paid works collection."""

import hashlib
import json
from uuid import UUID, uuid4

from app.collection.service import get, identity, insert
from app.connectors.creator_profiles import parse_identity, resolve
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.creators import active
from app.intelligence.refresh import ACTIONS
from app.tasks.service import Runner, TaskError, input_digest

KIND = "creator.resolve"
VERSION = "1"
PROFILE_INTERVAL = 10


class Resolve:
    action = "collection.run"

    def __init__(self, resolver=None, parser=None, version=VERSION):
        self.resolver, self.parser, self.version = resolver, parser, version

    def freeze(self, c, task, az):
        raw = az.read("raw_assets", task["raw_asset_id"])
        payload = json.loads(raw["body_text"])
        if (
            task["max_external_calls"] != 1
            or task["max_attempts"] != 1
            or payload["business"] != task["business_code"]
        ):
            raise TaskError("INVALID_INPUT")
        if not active(c, task["org_id"], payload["business"], payload["entry"]):
            raise TaskError("ACCESS_REVOKED")
        scopes = {("org", str(task["org_id"])), ("business", payload["business"])}
        if not all(az.allowed(a, scopes) for a in ACTIONS):
            raise TaskError("ACCESS_REVOKED")
        return payload

    def execute_ticket(self, runner, ticket, checkpoint):
        with runner.engine.begin() as c:
            task = runner.live(c, ticket)
            if not task:
                raise TaskError("ACCESS_REVOKED")
            runner.validate(c, task)
            exists = c.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM audit_events WHERE org_id=%s AND target_id=%s AND action_code='creator.profile.requested')",
                (ticket.org, ticket.task),
            ).scalar_one()
            if exists:
                raise TaskError("EXTERNAL_RESULT_UNKNOWN")
            # Database-wide persistent gate, including other orgs and process restarts.
            c.exec_driver_sql(
                "SELECT pg_advisory_xact_lock(hashtextextended('cip:creator-profile',0))"
            )
            recent = c.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM audit_events WHERE action_code='creator.profile.requested' "
                "AND occurred_at>clock_timestamp()-(%s * interval '1 second'))",
                (PROFILE_INTERVAL,),
            ).scalar_one()
            if recent:
                raise TaskError("RATE_LIMITED")
            c.execute(
                metadata.tables["audit_events"]
                .insert()
                .values(
                    id=uuid4(),
                    org_id=ticket.org,
                    actor_member_id=task["requested_by"],
                    action_code="creator.profile.requested",
                    target_kind="task",
                    target_id=ticket.task,
                    request_id=str(uuid4()),
                    safe_details={},
                    occurred_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
                )
            )
        reply = (self.resolver or resolve)(ticket.payload["entry"]["url"])
        # Preserve the external fact even when the task's authority/lease was revoked.
        with runner.engine.begin() as c:
            text = reply["body"]
            raw = insert(
                c,
                "raw_assets",
                ticket.org,
                origin="processing",
                asset_kind="response",
                processing_task_id=ticket.task,
                parent_raw_asset_id=task["raw_asset_id"],
                body_text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                captured_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
            )
            c.execute(
                metadata.tables["audit_events"]
                .insert()
                .values(
                    id=uuid4(),
                    org_id=ticket.org,
                    actor_member_id=task["requested_by"],
                    action_code="creator.profile.completed",
                    target_kind="task",
                    target_id=ticket.task,
                    request_id=str(uuid4()),
                    safe_details={"http_status": reply["status"], "error": reply["error"]},
                )
            )
        if reply["error"]:
            raise TaskError(reply["error"])
        checkpoint()
        return {"raw": str(raw)}

    def publish(self, c, task, result):
        raw = get(c, "raw_assets", task["org_id"], UUID(result["raw"]))
        payload = json.loads(
            get(c, "raw_assets", task["org_id"], task["raw_asset_id"])["body_text"]
        )
        if (
            raw["processing_task_id"] != task["id"]
            or raw["parent_raw_asset_id"] != task["raw_asset_id"]
        ):
            raise TaskError("INVALID_INPUT")
        data = (self.parser or parse_identity)(raw["body_text"], payload["entry"]["url"])
        account = identity(
            c,
            "external_accounts",
            task["org_id"],
            "platform_uid",
            data["uid"],
            display_name=data["name"] or None,
        )
        insert(
            c,
            "external_account_aliases",
            task["org_id"],
            account_id=account,
            alias_kind="sec_uid",
            alias_value=data["sec_uid"],
            raw_asset_id=raw["id"],
            observed_at=raw["captured_at"],
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"],
                task_id=task["id"],
                position=0,
                role="creator_identity",
                raw_asset_id=raw["id"],
            )
        )


def run_resolution(channels, entry, handler=None):
    channels.checkpoint()
    org = channels.p.org_id
    handler = handler or Resolve()
    with channels.runner.engine.begin() as c:
        parent = channels.runner.live(c, channels.ticket)
        if not parent or not active(c, org, channels.ticket.payload["business"], entry):
            raise TaskError("ACCESS_REVOKED")
        key_batch = getattr(channels, "resume_batch", channels.ticket.task)
        key = f"creator-resolve/{key_batch}/{entry['id']}/{handler.version}"
        tid = c.exec_driver_sql(
            "SELECT id FROM tasks WHERE org_id=%s AND idempotency_key=%s", (org, key)
        ).scalar_one_or_none()
        if not tid:
            payload = {"business": parent["business_code"], "entry": entry}
            text = json.dumps(payload, sort_keys=True)
            raw = insert(
                c,
                "raw_assets",
                org,
                origin="manual",
                asset_kind="response",
                submitted_by=channels.p.member_id,
                body_text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                captured_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
            )
            values = {
                "id": uuid4(),
                "org_id": org,
                "kind": KIND,
                "handler_version": handler.version,
                "raw_asset_id": raw,
                "business_code": parent["business_code"],
                "requested_by": channels.p.member_id,
                "execution_authorized_by": channels.p.member_id,
                "max_attempts": 1,
                "max_external_calls": 1,
                "idempotency_key": key,
            }
            values["input_sha256"] = input_digest(values, payload)
            tid, _ = create_task(c, values, [{"role": "creator_homepage", "raw_asset_id": raw}])
    runner = Runner(channels.runner.engine, {(KIND, handler.version): handler})
    state = runner.run(org, tid)
    if state != "succeeded":
        with channels.runner.engine.connect() as c:
            error = c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE org_id=%s AND id=%s", (org, tid)
            ).scalar_one()
        raise TaskError(error or "SOURCE_UNAVAILABLE")
