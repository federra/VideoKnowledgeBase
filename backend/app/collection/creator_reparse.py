"""Zero-HTTP recovery of complete directories whose detail request was blocked."""

import hashlib
import json
from uuid import UUID, uuid4

from app.collection.creator_series import CreatorSeries
from app.collection.service import insert
from app.connectors.douyin_series import CAPABILITY, VERSION, top
from app.core.repository import create_task
from app.intelligence.creators import active
from app.intelligence.refresh import ACTIONS, event, publish_channel
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.sessions import refresh
from app.tasks.service import Runner, TaskError, input_digest

KIND = "creator.series.reparse"


class Reparse:
    action = "collection.run"

    def freeze(self, c, task, az):
        raw = az.read("raw_assets", task["raw_asset_id"])
        manifest = json.loads(raw["body_text"])
        job = row(c, "collection_jobs", task["org_id"], UUID(manifest["job"]))
        original = row(c, "tasks", task["org_id"], job["task_id"])
        src = az.require("sources", job["source_id"], self.action)
        req = job["safe_request"]
        if (
            task["max_external_calls"] != 0
            or task["max_attempts"] != 1
            or task["source_id"] != job["source_id"]
            or task["business_code"] != job["business_code"]
            or job["business_date"] != shanghai_date()
            or job["capability_code"] != CAPABILITY
            or job["connector_version"] != VERSION
            or original["state"] != "failed"
            or original["safe_error_code"] != "INVALID_RESPONSE"
            or not active(c, task["org_id"], job["business_code"], req["entry"])
        ):
            raise TaskError("INVALID_INPUT")
        evidence = az.read("raw_assets", UUID(req["identity_evidence"]))
        raws = (
            c.exec_driver_sql(
                "SELECT r.*,cc.outcome,cc.sequence_no,cc.http_status FROM raw_assets r JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id WHERE r.org_id=%s AND r.collection_job_id=%s ORDER BY cc.sequence_no",
                (task["org_id"], job["id"]),
            )
            .mappings()
            .all()
        )
        pages, cursor = [], 0
        for r in raws:
            az.read("raw_assets", r["id"])
            if shanghai_date(r["captured_at"]) != job["business_date"]:
                raise TaskError("DATE_WINDOW_MISMATCH")
            try:
                body = json.loads(r["body_text"])
            except ValueError:
                continue
            if isinstance(body, dict) and "series_infos" in body:
                if r["outcome"] != "success":
                    raise TaskError("INVALID_INPUT")
                pages.append((cursor, body))
                cursor = body["cursor"]
        # Only this observed, known-completed failure may use recovery; no retries.
        if (
            not raws
            or raws[-1]["http_status"] != 200
            or raws[-1]["body_text"].strip() != "blocked"
            or raws[-1]["outcome"] != "invalid_shape"
        ):
            raise TaskError("INVALID_INPUT")
        batch = top(pages, req["sec_user_id"], req["uid"])
        return {
            "job": str(job["id"]),
            "source_version": src["lock_version"],
            "evidence": str(evidence["id"]),
            "raws": [(str(r["id"]), r["sha256"]) for r in raws],
            "unavailable": [r["platform_content_id"].split(":", 1)[1] for r in batch.records],
        }

    def execute(self, payload, checkpoint):
        checkpoint()
        return {
            "job": payload["job"],
            "samples": [],
            "unavailable": payload["unavailable"],
            "business_outcome": "insufficient_evidence",
        }

    def publish(self, c, task, result):
        job = row(c, "collection_jobs", task["org_id"], UUID(result["job"]))
        CreatorSeries(None).publish(c, task, result, original_job=job)


def reparse_batch(engine, p, batch_id):
    handler = Reparse()
    with engine.begin() as c:
        refresh(c, p)
        az = Authorizer(c, p)
        parent = az.check("tasks", batch_id, "task.read")
        manifest = json.loads(az.read("raw_assets", parent["raw_asset_id"])["body_text"])
        if (
            parent["kind"] != "intelligence.refresh"
            or parent["state"] != "succeeded"
            or not manifest.get("creators_only")
            or manifest["day"] != str(shanghai_date())
        ):
            raise TaskError("INVALID_INPUT")
        if not all(
            az.allowed(a, {("org", str(p.org_id)), ("business", parent["business_code"])})
            for a in ACTIONS
        ):
            raise TaskError("ACCESS_DENIED")
        jobs = (
            c.exec_driver_sql(
                "SELECT j.* FROM collection_jobs j JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id WHERE j.org_id=%s AND t.idempotency_key LIKE %s ORDER BY j.created_at",
                (p.org_id, f"refresh/{batch_id}/creators/%"),
            )
            .mappings()
            .all()
        )
        if not jobs or len(jobs) != len(manifest["creators"]):
            raise TaskError("INVALID_INPUT")
        ids = []
        for job in jobs:
            key = f"creator-reparse/{job['id']}"
            prior = c.exec_driver_sql(
                "SELECT id FROM tasks WHERE org_id=%s AND kind=%s AND idempotency_key=%s",
                (p.org_id, KIND, key),
            ).scalar_one_or_none()
            if prior:
                ids.append(prior)
                continue
            text = json.dumps({"job": str(job["id"])}, sort_keys=True)
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
                "kind": KIND,
                "handler_version": VERSION,
                "raw_asset_id": raw,
                "source_id": job["source_id"],
                "business_code": job["business_code"],
                "requested_by": p.member_id,
                "execution_authorized_by": p.member_id,
                "max_attempts": 1,
                "max_external_calls": 0,
                "idempotency_key": key,
            }
            frozen = handler.freeze(c, values, az)
            values["input_sha256"] = input_digest(values, frozen)
            inputs = list(
                dict.fromkeys(
                    [raw, UUID(frozen["evidence"]), *[UUID(r[0]) for r in frozen["raws"]]]
                )
            )
            tid, _ = create_task(
                c, values, [{"role": "reparse_evidence", "raw_asset_id": r} for r in inputs]
            )
            ids.append(tid)
    worker = Runner(engine, {(KIND, VERSION): handler})
    states = [worker.run(p.org_id, tid) for tid in ids]
    if any(s not in ("succeeded", "ignored") for s in states):
        raise TaskError("INVALID_RESPONSE")
    with engine.begin() as c:
        refresh(c, p)
        parent = row(c, "tasks", p.org_id, batch_id)
        az = Authorizer(c, p)
        if manifest["day"] != str(shanghai_date()) or not all(
            az.allowed(a, {("org", str(p.org_id)), ("business", parent["business_code"])})
            for a in ACTIONS
        ):
            raise TaskError("ACCESS_REVOKED")
        for tid in ids:
            task = row(c, "tasks", p.org_id, tid)
            if task["state"] != "succeeded":
                raise TaskError("SOURCE_UNAVAILABLE")
            worker.validate(c, task)
            output = c.exec_driver_sql(
                "SELECT r.body_text FROM task_outputs o JOIN raw_assets r ON r.org_id=o.org_id AND r.id=o.raw_asset_id WHERE o.org_id=%s AND o.task_id=%s AND o.role='creator_series_manifest'",
                (p.org_id, tid),
            ).scalar_one()
            snapshot = row(
                c, "intelligence_snapshots", p.org_id, UUID(json.loads(output)["snapshot"])
            )
            frozen = json.loads(row(c, "raw_assets", p.org_id, task["raw_asset_id"])["body_text"])
            if (
                not snapshot["sealed_at"]
                or snapshot["job_id"] != UUID(frozen["job"])
                or snapshot["business_date"] != shanghai_date()
            ):
                raise TaskError("INVALID_RESPONSE")
        # Append an explicit repair fact; old failed summaries and HTTP receipts remain immutable.
        event(
            c,
            parent,
            "creators",
            state="partial",
            completed=len(ids),
            total=len(ids),
            message=f"{len(ids)}位博主完整目录TOP10已零网络恢复；第1集评论通道受限，未伪造空评论",
        )
        publish_channel(c, parent, "creators")
    return ids
