"""One explicitly requested batch; child jobs own budgets, evidence and publication fences."""

import hashlib
import json
import time
from uuid import UUID, uuid4

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import compare_and_swap, create_task
from app.intelligence.refresh import ACTIONS, KIND, VERSION, event, publish_channel
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.sessions import MemberPrincipal, refresh
from app.tasks.service import Runner, TaskError, input_digest


def child_key(batch, channel, capability, request):
    from app.security.primitives import digest

    return f"refresh/{batch}/{channel}/{capability}/{digest(request)}"


def channel_names(payload):
    boards = () if payload.get("creators_only") else ("hongguo", "tikhub", "fanqie", "qidian") + (("microfilm",) if payload["business"] == "story_short" else ())
    boards += (("qimao",) if payload["business"] == "motion_comic" and any(s["capability_code"] == "novel.qimao.board" for s in payload.get("specs", [])) else ())
    return boards + (("creators",) if payload.get("creators") else ())


class Refresh:
    action = "collection.run"

    def freeze(self, c, task, az):
        raw = az.read("raw_assets", task["raw_asset_id"])
        payload = json.loads(raw["body_text"])
        if (
            task["kind"] != KIND
            or task["max_external_calls"] != 0
            or task["max_attempts"] != 1
            or payload["business"] != task["business_code"]
            or raw["submitted_by"] != task["requested_by"]
            or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
        ):
            raise TaskError("INVALID_INPUT")
        scopes = {("org", str(task["org_id"])), ("business", task["business_code"])}
        if not all(az.allowed(a, scopes) for a in ACTIONS):
            raise TaskError("ACCESS_REVOKED")
        # ACTIONS above requires whole-business authority, so source-specific grants
        # cannot authorize this batch. Check membership in one read on each heartbeat.
        ids = {UUID(spec["source_id"]) for spec in payload["specs"]}
        sources = (
            c.exec_driver_sql(
                "SELECT id,business_code FROM sources WHERE org_id=%s AND id=ANY(%s)",
                (task["org_id"], list(ids)),
            )
            .mappings()
            .all()
        )
        if len(sources) != len(ids) or any(
            src["business_code"] != task["business_code"] for src in sources
        ):
            raise TaskError("INVALID_INPUT")
        return payload

    def execute_ticket(self, runner, ticket, checkpoint):
        from app.intelligence.refresh_channels import Channels

        channels = Channels(runner, ticket, checkpoint)
        results = {}
        for name in channel_names(ticket.payload):
            checkpoint()
            if str(shanghai_date()) != ticket.payload["day"]:
                raise TaskError("DATE_WINDOW_MISMATCH")
            results[name] = channels.run(name)
        return {"channels": results}

    def publish(self, c, task, result):
        text = json.dumps(result, sort_keys=True)
        raw = insert(
            c,
            "raw_assets",
            task["org_id"],
            origin="processing",
            asset_kind="response",
            processing_task_id=task["id"],
            parent_raw_asset_id=task["raw_asset_id"],
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"],
                task_id=task["id"],
                position=0,
                role="refresh_summary",
                raw_asset_id=raw,
            )
        )


def runtime(engine):
    from app.intelligence.refresh_resume import RESUME_KIND, Resume

    return Runner(engine, {(KIND, VERSION): Refresh(), (RESUME_KIND, VERSION): Resume()}, lease_seconds=180)


class ChildJobs:
    def __init__(self, runner, ticket, checkpoint):
        self.runner, self.ticket, self.checkpoint = runner, ticket, checkpoint
        self.p = MemberPrincipal(ticket.org, self._task()["requested_by"])

    def _task(self):
        with self.runner.engine.connect() as c:
            return row(c, "tasks", self.ticket.org, self.ticket.task)

    def progress(self, channel, state, completed=0, total=0, message=""):
        self.checkpoint()
        with self.runner.engine.begin() as c:
            task = self.runner.live(c, self.ticket)
            if not task:
                raise TaskError("ACCESS_REVOKED")
            event(c, task, channel, state=state, completed=completed, total=total, message=message)

    def publish_channel(self, channel):
        self.checkpoint()
        if str(shanghai_date()) != self.ticket.payload["day"]:
            raise TaskError("DATE_WINDOW_MISMATCH")
        with self.runner.engine.begin() as c:
            task = self.runner.live(c, self.ticket)
            if not task:
                raise TaskError("ACCESS_REVOKED")
            publish_channel(c, task, channel)

    def wait(self, seconds):
        # Check authority while waiting; never cancel a provider cooldown.
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.checkpoint()
            time.sleep(min(1, max(0, end - time.monotonic())))

    def run_job(
        self,
        channel,
        spec,
        handler,
        kind,
        *,
        request=None,
        content_id=None,
        snapshot_id=None,
        evidence_raw=None,
    ):
        self.checkpoint()
        if str(shanghai_date()) != self.ticket.payload["day"]:
            raise TaskError("DATE_WINDOW_MISMATCH")
        request = request or spec["safe_request"]
        key = child_key(getattr(self, "resume_batch", self.ticket.task), channel, spec["capability_code"], request)
        from app.security.primitives import digest

        saved = None
        self.last_http_status = None
        try:
            with self.runner.engine.begin() as c:
                refresh(c, self.p)
                if not self.runner.live(c, self.ticket):
                    raise TaskError("ACCESS_REVOKED")
                old = (
                    c.exec_driver_sql(
                        "SELECT t.id,j.id job_id,j.source_id FROM tasks t JOIN collection_jobs j ON j.task_id=t.id AND j.org_id=t.org_id WHERE t.org_id=%s AND t.idempotency_key=%s",
                        (self.p.org_id, key),
                    )
                    .mappings()
                    .one_or_none()
                )
                if old:
                    saved = {
                        "task_id": old["id"],
                        "job_id": old["job_id"],
                        "source_id": old["source_id"],
                    }
                else:
                    source = UUID(spec["source_id"]) if spec.get("source_id") else None
                    az = Authorizer(c, self.p)
                    if source is None:
                        # Only comment sources for a verified new-batch board member may be created.
                        if (
                            channel != "hongguo"
                            or kind != "collect.hongguo"
                            or not content_id
                            or not snapshot_id
                        ):
                            raise TaskError("INVALID_INPUT")
                        source = c.exec_driver_sql(
                            "SELECT id FROM sources WHERE org_id=%s AND business_code=%s AND platform_code='hongguo' AND target_kind='content' AND content_id=%s ORDER BY created_at LIMIT 1",
                            (self.p.org_id, self.ticket.payload["business"], content_id),
                        ).scalar_one_or_none()
                        if source is None:
                            source = insert(
                                c,
                                "sources",
                                self.p.org_id,
                                name="红果评论 · " + request["series_id"],
                                business_code=self.ticket.payload["business"],
                                platform_code="hongguo",
                                target_kind="content",
                                content_id=content_id,
                                enabled=False,
                                created_by=self.p.member_id,
                            )
                    src = az.require("sources", source, "source.configure")
                    az.require("sources", source, "collection.run")
                    if src["business_code"] != self.ticket.payload["business"]:
                        raise TaskError("INVALID_INPUT")
                    if not src["enabled"]:
                        compare_and_swap(
                            c,
                            "sources",
                            self.p.org_id,
                            source,
                            src["lock_version"],
                            {"enabled": True},
                        )
                    tid = uuid4()
                    job = insert(
                        c,
                        "collection_jobs",
                        self.p.org_id,
                        source_id=source,
                        connection_id=UUID(spec["connection_id"]),
                        task_id=tid,
                        capability_code=spec["capability_code"],
                        connector_version=spec["connector_version"],
                        business_code=self.ticket.payload["business"],
                        business_date=shanghai_date(),
                        safe_request=request,
                        request_sha256=digest(request),
                        max_requests=1,
                        max_items=spec["max_items"],
                    )
                    values = {
                        "id": tid,
                        "org_id": self.p.org_id,
                        "kind": kind,
                        "handler_version": spec["connector_version"],
                        "source_id": source,
                        "business_code": self.ticket.payload["business"],
                        "requested_by": self.p.member_id,
                        "execution_authorized_by": self.p.member_id,
                        "max_attempts": 1,
                        "max_external_calls": 1,
                        "idempotency_key": key,
                    }
                    frozen = handler.freeze(
                        c, values, az, **({"snapshot_id": snapshot_id} if snapshot_id else {})
                    )
                    values["input_sha256"] = input_digest(values, frozen)
                    create_task(
                        c,
                        values,
                        [{"role": "comment_board_snapshot", "snapshot_id": snapshot_id}]
                        if snapshot_id
                        else [{"role": "creator_identity", "raw_asset_id": evidence_raw}]
                        if evidence_raw
                        else [],
                    )
                    saved = {"task_id": tid, "job_id": job, "source_id": source}
            worker = Runner(self.runner.engine, {(kind, spec["connector_version"]): handler})
            worker.run(self.p.org_id, saved["task_id"])
            with self.runner.engine.begin() as c:
                task = row(c, "tasks", self.p.org_id, saved["task_id"])
                if task["state"] != "succeeded":
                    self.last_http_status = c.exec_driver_sql(
                        "SELECT http_status FROM collection_calls WHERE org_id=%s AND job_id=%s ORDER BY sequence_no DESC LIMIT 1",
                        (self.p.org_id, saved["job_id"]),
                    ).scalar_one_or_none()
                    raise TaskError(task["safe_error_code"] or "SOURCE_UNAVAILABLE")
                raw = (
                    c.exec_driver_sql(
                        "SELECT * FROM raw_assets WHERE org_id=%s AND collection_job_id=%s ORDER BY captured_at DESC LIMIT 1",
                        (self.p.org_id, saved["job_id"]),
                    )
                    .mappings()
                    .one()
                )
            with self.runner.engine.begin() as c:
                Authorizer(c, self.p).read("raw_assets", raw["id"])
            return dict(raw), saved
        finally:
            if saved:
                with self.runner.engine.begin() as c:
                    src = row(c, "sources", self.p.org_id, saved["source_id"])
                    if src["enabled"]:
                        compare_and_swap(
                            c,
                            "sources",
                            self.p.org_id,
                            src["id"],
                            src["lock_version"],
                            {"enabled": False},
                        )
