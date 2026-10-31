"""Explicit same-day continuation; successful child keys and responses are reused."""

import hashlib
import json
from uuid import UUID, uuid4

from app.collection.service import insert
from app.core.repository import create_task
from app.intelligence.refresh import KIND, VERSION, authorize, publish_channel
from app.intelligence.refresh_channels import Channels
from app.intelligence.refresh_worker import Refresh
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.sessions import refresh
from app.security.storage import audit, lock_org
from app.tasks.service import Runner, TaskError, input_digest

RESUME_KIND = "intelligence.refresh.resume"


class ResumeChannels(Channels):
    def reuse_verified_font(self):
        from app.connectors.fontcodec import spec

        with self.runner.engine.connect() as c:
            ok = c.exec_driver_sql(
                "SELECT 1 FROM audit_events WHERE org_id=%s AND target_id=%s AND action_code='intelligence.refresh.font_verified' AND safe_details->>'font_sha256'=%s",
                (self.p.org_id, self.resume_batch, spec()["font_sha256"]),
            ).first()
        if not ok:
            raise TaskError("SOURCE_UNAVAILABLE")
        return []

    def publish_channel(self, channel):
        # Existing child snapshots retain their original batch key. Publication is
        # recorded against that key only after this authorized continuation finishes.
        with self.runner.engine.begin() as c:
            task = self.runner.live(c, self.ticket)
            if not task:
                raise TaskError("ACCESS_REVOKED")
            self.runner.validate(c, task)
            if str(shanghai_date()) != self.ticket.payload["day"]:
                raise TaskError("DATE_WINDOW_MISMATCH")
            publish_channel(c, task, channel)
            publish_channel(c, {**task, "id": UUID(self.ticket.payload["resume_from"])}, channel)


class Resume(Refresh):
    def freeze(self, c, task, az):
        raw = az.read("raw_assets", task["raw_asset_id"])
        payload = json.loads(raw["body_text"])
        original = row(c, "tasks", task["org_id"], UUID(payload["resume_from"]))
        original_raw = az.read("raw_assets", original["raw_asset_id"])
        frozen = json.loads(original_raw["body_text"])
        if (
            original["kind"] != KIND
            or original["state"] != "failed"
            or original["business_code"] != task["business_code"]
            or frozen["day"] != str(shanghai_date())
            or payload != {**frozen, "resume_from": str(original["id"])}
            or task["max_external_calls"] != 0
            or task["max_attempts"] != 1
            or raw["submitted_by"] != task["requested_by"]
            or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
        ):
            raise TaskError("INVALID_INPUT")
        # Apply the normal authority and source membership checks without changing
        # the original frozen task or borrowing an expired browser session.
        super().freeze(c, {**task, "kind": KIND}, az)
        return payload

    def execute_ticket(self, runner, ticket, checkpoint):
        original = UUID(ticket.payload["resume_from"])
        channels = ResumeChannels(runner, ticket, checkpoint)
        channels.resume_batch = original
        with runner.engine.connect() as c:
            done = set(
                c.exec_driver_sql(
                    "SELECT safe_details->>'code' FROM audit_events WHERE org_id=%s AND target_id=%s AND action_code='intelligence.refresh.published'",
                    (ticket.org, original),
                ).scalars()
            )
        results = {}
        from app.intelligence.refresh_worker import channel_names

        for channel in channel_names(ticket.payload):
            checkpoint()
            if channel in done:
                channels.progress(channel, "succeeded", message="复用原批次已完成数据；未重复请求")
                results[channel] = "reused"
            else:
                results[channel] = channels.run(channel)
        return {"channels": results}


def check_creator_entry(c, org, original):
    # Creator directory recovery has independent identity keys. Until that
    # recovery is explicitly supported, refuse a partially attempted creator
    # channel rather than risk repeating a successful page or identity lookup.
    attempted = c.exec_driver_sql(
        "SELECT 1 FROM tasks WHERE org_id=%s AND (idempotency_key LIKE %s OR idempotency_key LIKE %s) LIMIT 1",
        (
            org,
            "refresh/" + str(original) + "/creators/%%",
            "creator-resolve/" + str(original) + "/%%",
        ),
    ).first()
    creator_done = c.exec_driver_sql(
        "SELECT 1 FROM audit_events WHERE org_id=%s AND target_id=%s AND action_code='intelligence.refresh.published' AND safe_details->>'code'='creators'",
        (org, original),
    ).first()
    previous_attempt = c.exec_driver_sql(
        "SELECT 1 FROM tasks child JOIN tasks parent ON parent.org_id=child.org_id JOIN raw_assets r ON r.org_id=parent.org_id AND r.id=parent.raw_asset_id WHERE parent.org_id=%s AND parent.kind=%s AND r.body_text::jsonb->>'resume_from'=%s AND (child.idempotency_key LIKE 'refresh/'||parent.id::text||'/creators/%%' OR child.idempotency_key LIKE 'creator-resolve/'||parent.id::text||'/%%') LIMIT 1",
        (org, RESUME_KIND, str(original)),
    ).first()
    if (attempted or previous_attempt) and not creator_done:
        raise TaskError("INVALID_INPUT")


def start_resume(c, p, original_id):
    lock_org(c, p.org_id)
    refresh(c, p)
    original = row(c, "tasks", p.org_id, original_id)
    authorize(c, p, original["business_code"])
    if c.exec_driver_sql(
        "SELECT 1 FROM tasks WHERE org_id=%s AND kind IN ('intelligence.refresh','intelligence.refresh.resume') AND state IN ('queued','running','cancel_requested')",
        (p.org_id,),
    ).first():
        raise TaskError("INVALID_INPUT")
    check_creator_entry(c, p.org_id, original_id)
    payload = json.loads(row(c, "raw_assets", p.org_id, original["raw_asset_id"])["body_text"])
    payload["resume_from"] = str(original_id)
    text = json.dumps(payload, sort_keys=True)
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
    values = {
        "id": uuid4(),
        "org_id": p.org_id,
        "kind": RESUME_KIND,
        "handler_version": VERSION,
        "raw_asset_id": raw,
        "business_code": original["business_code"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_attempts": 1,
        "max_external_calls": 0,
        "idempotency_key": "resume/" + str(original_id) + "/" + str(uuid4()),
    }
    Resume().freeze(
        c,
        values,
        Authorizer(c, p),
    )
    values["input_sha256"] = input_digest(values, payload)
    tid, _ = create_task(
        c,
        values,
        [
            {"role": "resume_plan", "raw_asset_id": raw},
            {"role": "original_plan", "raw_asset_id": original["raw_asset_id"]},
        ],
    )
    audit(c, p.org_id, p.member_id, "intelligence.refresh.resume.requested", "task", tid)
    return tid


def runner(engine):
    return Runner(engine, {(RESUME_KIND, VERSION): Resume()}, lease_seconds=180)
