"""Explicit dedicated-browser comments for a frozen, authorized creator TOP snapshot."""

import asyncio
import hashlib
import json
import os
from datetime import datetime
from uuid import UUID, uuid4

from app.collection.service import insert
from app.connectors.douyin_browser_session import (
    BINARIES,
    exclusive_profile,
    guarded_capture,
    open_context,
    sample_bundle,
)
from app.connectors.douyin_series import CAPABILITY
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.creator_directory import require_directory
from app.intelligence.creators import active
from app.intelligence.refresh import ACTIONS
from app.intelligence.service import authorized, row, shanghai_date
from app.security.authorization import Authorizer
from app.security.sessions import refresh
from app.tasks.service import Runner, TaskError, input_digest

KIND = "creator.browser.comments"
VERSION = "1"
ROLE = "creator_browser_manifest"


def bundle_from_capture(data):
    responses = [data["episode_response"], *data["comment_responses"]]
    result = sample_bundle([r for r in responses if r], data["series_id"], data["uid"])
    if (
        data.get("method") != "dedicated_browser_network_json"
        or data.get("status") != "sampled"
        or not (result["sample_complete"] or result["comments"])
        or result["aweme_id"] != data.get("aweme_id")
    ):
        raise TaskError("INVALID_RESPONSE")
    return result


class BrowserComments:
    action = "collection.run"

    def __init__(self, visitor=None, *, headed=False):
        self.visitor, self.headed = visitor, headed

    def freeze(self, c, task, az):
        manifest = json.loads(az.read("raw_assets", task["raw_asset_id"])["body_text"])
        snap = row(c, "intelligence_snapshots", task["org_id"], UUID(manifest["snapshot"]))
        job = row(c, "collection_jobs", task["org_id"], snap["job_id"])
        src = az.require("sources", snap["source_id"], self.action)
        p = az.p
        scopes = {
            ("org", str(p.org_id)),
            ("business", snap["business_code"]),
            ("source", str(src["id"])),
        }
        if (
            not snap["sealed_at"]
            or snap["business_date"] != shanghai_date()
            or job["capability_code"] != CAPABILITY
            or task["source_id"] != src["id"]
            or task["business_code"] != snap["business_code"]
            or task["max_attempts"] != 1
            or not (
                task["max_external_calls"] == 0
                if getattr(self, "reparse", False)
                else 1 <= task["max_external_calls"] <= 10
            )
            or not all(az.allowed(a, scopes) for a in ACTIONS)
            or not active(c, p.org_id, snap["business_code"], job["safe_request"]["entry"])
        ):
            raise TaskError("ACCESS_REVOKED")
        authorized(c, p, snap)
        require_directory(c, p, job, az)
        rows = (
            c.exec_driver_sql(
                "SELECT ec.id,ec.platform_content_id FROM snapshot_entries e JOIN content_observations co ON co.org_id=e.org_id AND co.id=e.content_observation_id JOIN external_contents ec ON ec.org_id=co.org_id AND ec.id=co.content_id WHERE e.org_id=%s AND e.snapshot_id=%s ORDER BY e.position",
                (p.org_id, snap["id"]),
            )
            .mappings()
            .all()
        )
        targets = manifest["targets"]
        available = {str(r["id"]): r["platform_content_id"].split(":", 1)[1] for r in rows}
        if (
            not targets
            or len(targets)
            != (1 if getattr(self, "reparse", False) else task["max_external_calls"])
            or len({t["content"] for t in targets}) != len(targets)
            or any(available.get(t["content"]) != t["series_id"] for t in targets)
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "snapshot": str(snap["id"]),
            "day": str(snap["business_date"]),
            "uid": job["safe_request"]["uid"],
            "source_version": src["lock_version"],
            "targets": targets,
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        def fence():
            checkpoint()
            with runner.engine.begin() as c:
                task = runner.live(c, ticket)
                if not task:
                    raise TaskError("ACCESS_REVOKED")
                runner.validate(c, task)

        results = []

        async def launch():
            if self.visitor:
                return await collect(None)
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BINARIES))
            from playwright.async_api import async_playwright

            with exclusive_profile():
                async with async_playwright() as p:
                    context = await open_context(p, headless=not self.headed)
                    try:
                        await collect(context)
                    finally:
                        await context.close()

        async def collect(context):
            for i, target in enumerate(ticket.payload["targets"]):
                fence()

                def reserve(sequence=i):
                    fence()
                    with runner.engine.begin() as c:
                        task = runner.live(c, ticket)
                        runner.validate(c, task)
                        count = c.exec_driver_sql(
                            "SELECT count(*) FROM audit_events WHERE org_id=%s AND target_id=%s AND action_code='creator.browser.requested'",
                            (ticket.org, ticket.task),
                        ).scalar_one()
                        if count != sequence or count >= task["max_external_calls"]:
                            raise TaskError("EXTERNAL_RESULT_UNKNOWN")
                        visit_event(
                            c, ticket, task["requested_by"], "requested", {"sequence": sequence}
                        )

                if self.visitor:
                    reserve()
                    data = self.visitor(target["series_id"], ticket.payload["uid"])
                else:
                    data = await guarded_capture(
                        context,
                        target["series_id"],
                        ticket.payload["uid"],
                        before_request=fence,
                        on_request=reserve,
                    )
                data.update(snapshot_id=ticket.payload["snapshot"])
                text = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
                with runner.engine.begin() as c:
                    raw = insert(
                        c,
                        "raw_assets",
                        ticket.org,
                        origin="processing",
                        asset_kind="response",
                        processing_task_id=ticket.task,
                        parent_raw_asset_id=task_input(runner, c, ticket),
                        external_content_id=UUID(target["content"]),
                        body_text=text,
                        sha256=hashlib.sha256(text.encode()).hexdigest(),
                        captured_at=datetime.fromisoformat(data["captured_at"]),
                    )
                    visit_event(
                        c, ticket, None, "completed", {"sequence": i, "status": data["status"]}
                    )
                results.append(
                    {
                        "series_id": target["series_id"],
                        "content": target["content"],
                        "raw": str(raw),
                        "status": data["status"],
                    }
                )
                fence()
                if data.get("safe_error"):
                    raise TaskError(data["safe_error"])
                if data["status"] != "sampled":
                    break

        asyncio.run(launch())
        return {
            "snapshot": ticket.payload["snapshot"],
            "captures": results,
            "business_outcome": "completed"
            if len(results) == len(ticket.payload["targets"])
            and all(r["status"] == "sampled" for r in results)
            else "insufficient_evidence",
        }

    def publish(self, c, task, result):
        manifest = json.loads(
            row(c, "raw_assets", task["org_id"], task["raw_asset_id"])["body_text"]
        )
        snapshot = row(c, "intelligence_snapshots", task["org_id"], UUID(manifest["snapshot"]))
        job = row(c, "collection_jobs", task["org_id"], snapshot["job_id"])
        expected = {t["series_id"]: t["content"] for t in manifest["targets"]}
        parent = (
            UUID(manifest["saved_capture"])
            if getattr(self, "reparse", False)
            else task["raw_asset_id"]
        )
        for captured in result["captures"]:
            raw = row(c, "raw_assets", task["org_id"], UUID(captured["raw"]))
            data = json.loads(raw["body_text"])
            if (
                raw["processing_task_id"] != task["id"]
                or raw["parent_raw_asset_id"] != parent
                or str(raw["external_content_id"]) != expected.get(data["series_id"])
                or data["snapshot_id"] != manifest["snapshot"]
                or data["uid"] != job["safe_request"]["uid"]
                or shanghai_date(raw["captured_at"]) != shanghai_date()
            ):
                raise TaskError("INVALID_RESPONSE")
            if data["status"] == "sampled":
                bundle = bundle_from_capture(data)
                for value in bundle["comments"]:
                    insert(
                        c,
                        "comment_evidence",
                        task["org_id"],
                        content_id=raw["external_content_id"],
                        raw_asset_id=raw["id"],
                        captured_at=raw["captured_at"],
                        **value,
                    )
        text = json.dumps(result, sort_keys=True)
        raw = insert(
            c,
            "raw_assets",
            task["org_id"],
            origin="processing",
            asset_kind="response",
            processing_task_id=task["id"],
            parent_raw_asset_id=parent,
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"], task_id=task["id"], position=0, role=ROLE, raw_asset_id=raw
            )
        )


def visit_event(c, ticket, actor, phase, details):
    c.execute(
        metadata.tables["audit_events"]
        .insert()
        .values(
            id=uuid4(),
            org_id=ticket.org,
            actor_member_id=actor,
            action_code="creator.browser." + phase,
            target_kind="task",
            target_id=ticket.task,
            request_id=str(uuid4()),
            safe_details=details,
        )
    )


def task_input(runner, c, ticket):
    return row(c, "tasks", ticket.org, ticket.task)["raw_asset_id"]


def submit(c, p, snapshot_id, *, limit=10, offset=0, handler=None):
    refresh(c, p)
    handler = handler or BrowserComments()
    snap = row(c, "intelligence_snapshots", p.org_id, snapshot_id)
    targets = (
        c.exec_driver_sql(
            "SELECT ec.id,ec.platform_content_id FROM snapshot_entries e JOIN content_observations co ON co.org_id=e.org_id AND co.id=e.content_observation_id JOIN external_contents ec ON ec.org_id=co.org_id AND ec.id=co.content_id WHERE e.org_id=%s AND e.snapshot_id=%s ORDER BY e.position LIMIT %s OFFSET %s",
            (p.org_id, snapshot_id, limit, offset),
        )
        .mappings()
        .all()
    )
    if not 1 <= limit <= 10 or not 0 <= offset < 10 or not targets:
        raise TaskError("INVALID_INPUT")
    text = json.dumps(
        {
            "snapshot": str(snapshot_id),
            "targets": [
                {"content": str(t["id"]), "series_id": t["platform_content_id"].split(":", 1)[1]}
                for t in targets
            ],
        },
        sort_keys=True,
    )
    raw = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="manual",
        asset_kind="response",
        submitted_by=p.member_id,
        body_text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        captured_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
    )
    task = {
        "id": uuid4(),
        "org_id": p.org_id,
        "kind": KIND,
        "handler_version": VERSION,
        "raw_asset_id": raw,
        "source_id": snap["source_id"],
        "business_code": snap["business_code"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_attempts": 1,
        "max_external_calls": len(targets),
        "idempotency_key": f"creator-browser/{snapshot_id}/{uuid4()}",
    }
    task["input_sha256"] = input_digest(task, handler.freeze(c, task, Authorizer(c, p)))
    return create_task(c, task, [{"role": "creator_browser_selection", "raw_asset_id": raw}])[0]


def run(engine, p, snapshot_ids, *, limit=10, offset=0, handler=None):
    handler = handler or BrowserComments()
    results = []
    for sid in snapshot_ids:
        with engine.begin() as c:
            tid = submit(c, p, sid, limit=limit, offset=offset, handler=handler)
        state = Runner(engine, {(KIND, VERSION): handler}).run(p.org_id, tid)
        results.append({"task": str(tid), "state": state})
        if state != "succeeded":
            break
        with engine.connect() as c:
            task = row(c, "tasks", p.org_id, tid)
            if task["business_outcome"] != "completed":
                break
    return results
