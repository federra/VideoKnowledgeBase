"""Strict zero-network repair of an already captured source sampling window."""

import hashlib
import json
from uuid import UUID, uuid4

from app.collection.creator_browser_comments import (
    KIND as CAPTURE_KIND,
)
from app.collection.creator_browser_comments import (
    VERSION,
    BrowserComments,
    bundle_from_capture,
)
from app.collection.service import insert
from app.core.repository import create_task
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.sessions import refresh
from app.tasks.service import Runner, TaskError, input_digest

KIND = "creator.browser.reparse"


class BrowserReparse(BrowserComments):
    reparse = True

    def freeze(self, c, task, az):
        frozen = super().freeze(c, task, az)
        manifest = json.loads(az.read("raw_assets", task["raw_asset_id"])["body_text"])
        raw = az.read("raw_assets", UUID(manifest["saved_capture"]))
        original = row(c, "tasks", task["org_id"], raw["processing_task_id"])
        data = json.loads(raw["body_text"])
        target = frozen["targets"][0]
        prior_manifest = json.loads(az.read("raw_assets", original["raw_asset_id"])["body_text"])
        sequence = next(
            (i for i, value in enumerate(prior_manifest.get("targets", [])) if value == target),
            None,
        )
        confirmed = False
        if (
            original["state"] == "failed"
            and original["safe_error_code"] in ("EXTERNAL_RESULT_UNKNOWN", "FETCH_FAILED")
            and data["status"] == "sampled"
            and prior_manifest.get("snapshot") == frozen["snapshot"]
            and sequence is not None
        ):
            # A later visit can fail while this earlier raw was durably acknowledged.
            # Reuse only its matching completed sequence; never reissue the unknown visit.
            confirmed = c.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM audit_events WHERE org_id=%s AND target_id=%s "
                "AND action_code='creator.browser.completed' AND safe_details->>'status'='sampled' "
                "AND safe_details->>'sequence'=%s AND created_at>=%s)",
                (task["org_id"], original["id"], str(sequence), raw["created_at"]),
            ).scalar_one()
        legacy_partial = (
            original["state"] == "succeeded"
            and original["business_outcome"] == "insufficient_evidence"
            and data["status"] == "session_not_ready"
        )
        if (
            task["kind"] != KIND
            or original["kind"] != CAPTURE_KIND
            or not (legacy_partial or confirmed)
            or original["source_id"] != task["source_id"]
            or original["business_code"] != task["business_code"]
            or data.get("safe_error")
            or data["snapshot_id"] != frozen["snapshot"]
            or data["uid"] != frozen["uid"]
            or data["series_id"] != target["series_id"]
            or str(raw["external_content_id"]) != target["content"]
            or shanghai_date(raw["captured_at"]) != shanghai_date()
            or any(r.get("status") in (403, 429) for r in data.get("diagnostics", []))
        ):
            raise TaskError("INVALID_INPUT")
        data["status"] = "sampled"
        bundle_from_capture(data)
        return {**frozen, "saved_capture": str(raw["id"]), "saved_sha256": raw["sha256"]}

    def execute_ticket(self, runner, ticket, checkpoint):
        checkpoint()
        with runner.engine.begin() as c:
            task = runner.live(c, ticket)
            runner.validate(c, task)
            old = row(c, "raw_assets", ticket.org, UUID(ticket.payload["saved_capture"]))
            data = json.loads(old["body_text"])
            data["status"] = "sampled"
            bundle = bundle_from_capture(data)
            data.update(
                comments=bundle["comments"],
                sample_complete=bundle["sample_complete"],
                reparsed_from=str(old["id"]),
            )
            text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
            raw = insert(
                c,
                "raw_assets",
                ticket.org,
                origin="processing",
                asset_kind="response",
                processing_task_id=ticket.task,
                parent_raw_asset_id=old["id"],
                external_content_id=old["external_content_id"],
                body_text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                captured_at=old["captured_at"],
            )
        checkpoint()
        target = ticket.payload["targets"][0]
        return {
            "snapshot": ticket.payload["snapshot"],
            "captures": [{**target, "raw": str(raw), "status": "sampled"}],
            "business_outcome": "completed",
        }


def repair(engine, p, raw_id):
    handler = BrowserReparse()
    with engine.begin() as c:
        refresh(c, p)
        az = Authorizer(c, p)
        original = az.read("raw_assets", raw_id)
        data = json.loads(original["body_text"])
        snap = row(c, "intelligence_snapshots", p.org_id, UUID(data["snapshot_id"]))
        text = json.dumps(
            {
                "snapshot": str(snap["id"]),
                "saved_capture": str(raw_id),
                "targets": [
                    {
                        "content": str(original["external_content_id"]),
                        "series_id": data["series_id"],
                    }
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
            "max_external_calls": 0,
            "idempotency_key": f"creator-browser-reparse/{raw_id}/{uuid4()}",
        }
        task["input_sha256"] = input_digest(task, handler.freeze(c, task, az))
        tid = create_task(
            c,
            task,
            [
                {"role": "selection", "raw_asset_id": raw},
                {"role": "saved_capture", "raw_asset_id": raw_id},
            ],
        )[0]
    return {
        "task": str(tid),
        "state": Runner(engine, {(KIND, VERSION): handler}).run(p.org_id, tid),
    }
