"""Fenced microfilm search plus bounded comment samples; acquired prefixes can publish."""

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func

from app.collection.handler import publish_batch
from app.collection.service import get, insert
from app.connectors import douyin_search as ds
from app.connectors.redfox import AdapterError
from app.core.models import metadata
from app.core.repository import compare_and_swap, create_task
from app.intelligence.service import shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.tasks.service import Runner, TaskError, input_digest

BOARD = "douyin-microfilm-comprehensive"
NAME = "微电影 · 抖音综合搜索TOP50"


def saved(c, org, job, az=None):
    rows = (
        c.exec_driver_sql(
            "SELECT r.*,cc.sequence_no,cc.outcome FROM raw_assets r JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id WHERE r.org_id=%s AND r.collection_job_id=%s ORDER BY cc.sequence_no",
            (org, job["id"]),
        )
        .mappings()
        .all()
    )
    from app.collection.page_resume import reuse_rows

    rows = list(reuse_rows(c, org, job, az)) + list(rows)
    pages, assets, comments, rawmap = [], {}, {}, {}
    for raw in rows:
        if raw["outcome"] != "success":
            continue
        if az:
            az.read("raw_assets", raw["id"])
        if shanghai_date(raw["captured_at"]) != job["business_date"]:
            raise TaskError("DATE_WINDOW_MISMATCH")
        value = json.loads(raw["body_text"])
        rawmap[str(raw["id"])] = raw
        if value.get("kind") == "search":
            pages.append(value)
            for r in ds.search_page(value).records:
                assets.setdefault(r["platform_content_id"], raw)
        elif value.get("kind") == "comments":
            aid = value["parameters"]["aweme_id"]
            comments.setdefault(aid, []).append((raw, value))
    return pages, assets, comments, rawmap


def comment_rows(pages, aid):
    cursor, seen, rows = 0, set(), []
    for raw, value in pages:
        requested = int(value["parameters"].get("cursor", 0))
        if requested != cursor:
            raise AdapterError("INVALID_RESPONSE")
        for row in ds.comment_page(value, aid):
            if row["platform_comment_id"] not in seen and len(rows) < 15:
                seen.add(row["platform_comment_id"])
                rows.append((raw, row))
        b = value["body"]
        if len(rows) >= 15 or b.get("has_more") == 0:
            break
        cursor = b.get("cursor")
        if type(cursor) is not int or cursor <= requested or cursor >= 15:
            break
    return rows


class Microfilm:
    action = "collection.run"

    def __init__(self, connector_factory=None, parent_checkpoint=None):
        self.connector_factory = connector_factory
        self.parent_checkpoint = parent_checkpoint

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
        req = job["safe_request"]
        plan = az.read("raw_assets", task["raw_asset_id"])
        if json.loads(plan["body_text"]) != req or plan["submitted_by"] != task["requested_by"]:
            raise TaskError("INVALID_INPUT")
        if (
            not source["enabled"]
            or source["board_code"] != BOARD
            or source["target_kind"] != "board"
            or source["business_code"] != "story_short"
            or task["business_code"] != "story_short"
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "douyin_session"
            or conn["secret_ref"] != "LOCAL_DOUYIN_BROWSER_SESSION"
            or job["capability_code"] != ds.CAPABILITY
            or job["connector_version"] != ds.VERSION
            or job["plan_id"] is not None
            or req != {**ds.REQUEST, "one_off_retry": req.get("one_off_retry")}
            or type(req.get("one_off_retry")) is not bool
            or job["max_requests"] != ds.MAX_CALLS
            or job["max_items"] != 50
            or task["max_external_calls"] != ds.MAX_CALLS
            or task["max_attempts"] != 1
            or digest(req) != job["request_sha256"]
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "request": req,
            "day": str(job["business_date"]),
            "source_version": source["lock_version"],
            "connection_version": conn["lock_version"],
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        try:
            return self._execute_ticket(runner, ticket, checkpoint)
        except AdapterError as exc:
            raise TaskError(str(exc)) from None

    def _execute_ticket(self, runner, ticket, checkpoint):
        def fence():
            if self.parent_checkpoint:
                self.parent_checkpoint()
            checkpoint()
            if str(shanghai_date()) != ticket.payload["day"]:
                raise TaskError("DATE_WINDOW_MISMATCH")

        factory = self.connector_factory
        if factory is None:
            from app.connectors.douyin_search_session import SearchSession

            factory = SearchSession
        job_id = UUID(ticket.payload["job_id"])
        failures = 0
        verification_required = False
        pages = []
        count = 0
        reused = {r["request_sha256"]: r["value"] for r in ticket.payload.get("reused_pages", [])}
        with factory(one_off_retry=ticket.payload["request"]["one_off_retry"]) as connector:
            connector.before_request = fence

            def request(kind, target, cursor=0, search_id=""):
                nonlocal failures, count, verification_required
                reuse_key = digest(
                    {"kind": kind, "target": target, "cursor": cursor, "search_id": search_id}
                )
                if reuse_key in reused:
                    fence()
                    return reused[reuse_key]
                while count < ds.MAX_CALLS:
                    fence()
                    count += 1
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
                            sequence_no=count,
                            request_sha256=digest(
                                {
                                    "kind": kind,
                                    "target": target,
                                    "cursor": cursor,
                                    "search_id": search_id,
                                }
                            ),
                        )
                    reply = connector.fetch(kind, target, cursor, search_id)
                    if not reply.error:
                        try:
                            value = json.loads(reply.raw_text)
                            if kind == "search":
                                ds.combine(pages + [value])
                            else:
                                ds.comment_page(value, target)
                                if int(value["parameters"].get("cursor", 0)) != cursor:
                                    raise AdapterError("INVALID_RESPONSE")
                        except (ValueError, KeyError, TypeError, AttributeError):
                            reply.error, reply.outcome = "INVALID_RESPONSE", "invalid_shape"
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
                    if not reply.error:
                        return json.loads(reply.raw_text)
                    if reply.error == "SOURCE_VERIFICATION_REQUIRED":
                        verification_required = True
                        raise TaskError(reply.error)
                    failures += 1
                    if not ticket.payload["request"]["one_off_retry"] or failures >= 2:
                        raise TaskError(reply.error)
                raise TaskError("BUDGET_EXHAUSTED")

            cursor, search_id = 0, ""
            try:
                for _ in range(ds.MAX_PAGES):
                    value = request("search", "微电影", cursor, search_id)
                    pages.append(value)
                    batch, complete = ds.combine(pages)
                    if complete:
                        break
                    cursor = value["body"]["cursor"]
                    search_id = (value["body"].get("extra") or {}).get("logid", "")
            except TaskError as exc:
                if exc.code in ("ACCESS_REVOKED", "DATE_WINDOW_MISMATCH") or not pages:
                    raise
            batch, complete = ds.combine(pages)
            if batch.records and failures < 2 and not verification_required:
                for record in batch.records:
                    aid = record["platform_content_id"]
                    try:
                        value = request("comments", aid)
                        sample = ds.comment_page(value, aid)
                        b = value["body"]
                        cursor = b.get("cursor")
                        if (
                            len(sample) < 15
                            and b.get("has_more") == 1
                            and type(cursor) is int
                            and 0 < cursor < 15
                        ):
                            request("comments", aid, cursor)
                    except (TaskError, AdapterError) as exc:
                        if isinstance(exc, TaskError) and exc.code in (
                            "ACCESS_REVOKED",
                            "DATE_WINDOW_MISMATCH",
                        ):
                            raise
                        break
            fence()
            return {
                "business_outcome": "completed"
                if complete and not failures and not verification_required
                else "insufficient_evidence",
                "search_complete": complete,
                "verification_required": verification_required,
                "failed_attempts": failures,
                "items": len(batch.records),
            }

    def publish(self, c, task, result):
        org = task["org_id"]
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, task["id"])
            )
            .mappings()
            .one()
        )
        pages, assets, samples, _ = saved(c, org, job)
        batch, complete = ds.combine(pages)
        if not batch.records and not complete:
            raise TaskError("INVALID_RESPONSE")
        first = next(iter(assets.values()), None)
        if first is None:
            first = (
                c.exec_driver_sql(
                    "SELECT r.* FROM raw_assets r JOIN collection_calls cc ON cc.id=r.collection_call_id WHERE r.collection_job_id=%s AND cc.outcome='success' ORDER BY cc.sequence_no LIMIT 1",
                    (job["id"],),
                )
                .mappings()
                .one()
            )
        snapshot = publish_batch(c, task, first, job, batch, record_assets=assets)
        counts = {}
        manifest = {}
        for record in batch.records:
            aid = record["platform_content_id"]
            acquired = samples.get(aid, [])
            if not acquired:
                continue
            rows = comment_rows(acquired, aid)
            counts[aid] = len(rows)
            manifest[aid] = [str(r["id"]) for r, _ in acquired]
            content = c.exec_driver_sql(
                "SELECT id FROM external_contents WHERE org_id=%s AND platform_code='douyin' AND platform_content_id=%s",
                (org, aid),
            ).scalar_one()
            per_raw = {}
            for raw, row in rows:
                position = per_raw.get(raw["id"], 0)
                per_raw[raw["id"]] = position + 1
                if raw["collection_job_id"] != job["id"]:
                    existing = (
                        c.exec_driver_sql(
                            "SELECT content_id,body_text,platform_comment_id FROM comment_evidence WHERE org_id=%s AND raw_asset_id=%s AND sample_position=%s",
                            (org, raw["id"], position),
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing:
                        if existing["content_id"] != content or any(
                            existing[k] != row[k] for k in ("body_text", "platform_comment_id")
                        ):
                            raise TaskError("INVALID_INPUT")
                        continue
                insert(
                    c,
                    "comment_evidence",
                    org,
                    content_id=content,
                    raw_asset_id=raw["id"],
                    captured_at=raw["captured_at"],
                    **{**row, "sample_position": position},
                )
        payload = {
            "snapshot": str(snapshot),
            "search_complete": complete,
            "comments": manifest,
            "comment_counts": counts,
            "failed_attempts": result["failed_attempts"],
            "acquired": len(batch.records),
            "requested": 50,
            "verification_required": bool(result.get("verification_required")),
        }
        text = json.dumps(payload, sort_keys=True)
        raw = insert(
            c,
            "raw_assets",
            org,
            origin="processing",
            asset_kind="response",
            processing_task_id=task["id"],
            parent_raw_asset_id=task["raw_asset_id"],
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=func.clock_timestamp(),
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=org,
                task_id=task["id"],
                position=1,
                role="microfilm_manifest",
                raw_asset_id=raw,
            )
        )


def submit(c, p, key, handler, *, one_off_retry=False):
    refresh(c, p)
    az = Authorizer(c, p)
    for action in (
        "source.configure",
        "collection.run",
        "content.read",
        "evidence.read",
        "task.read",
    ):
        if not az.allowed(action, {("org", str(p.org_id)), ("business", "story_short")}):
            raise TaskError("ACCESS_REVOKED")
    existing = c.exec_driver_sql(
        "SELECT id,source_id FROM tasks WHERE org_id=%s AND idempotency_key=%s", (p.org_id, key)
    ).first()
    if existing:
        az.require("sources", existing[1], "source.configure")
        frozen = c.exec_driver_sql(
            "SELECT safe_request FROM collection_jobs WHERE org_id=%s AND task_id=%s",
            (p.org_id, existing[0]),
        ).scalar_one()
        if frozen.get("one_off_retry") != one_off_retry:
            raise TaskError("IDEMPOTENCY_CONFLICT")
        return existing[0], existing[1]
    conn = c.exec_driver_sql(
        "SELECT id FROM provider_connections WHERE org_id=%s AND provider_code='douyin_session' ORDER BY created_at LIMIT 1",
        (p.org_id,),
    ).scalar_one_or_none()
    if conn is None:
        conn = insert(
            c,
            "provider_connections",
            p.org_id,
            name="抖音独立会话JSON",
            provider_code="douyin_session",
            secret_ref="LOCAL_DOUYIN_BROWSER_SESSION",
            enabled=True,
        )
    source = c.exec_driver_sql(
        "SELECT id FROM sources WHERE org_id=%s AND business_code='story_short' AND platform_code='douyin' AND board_code=%s AND archived_at IS NULL ORDER BY created_at LIMIT 1",
        (p.org_id, BOARD),
    ).scalar_one_or_none()
    if source is None:
        source = insert(
            c,
            "sources",
            p.org_id,
            name=NAME,
            business_code="story_short",
            platform_code="douyin",
            target_kind="board",
            board_code=BOARD,
            enabled=False,
            created_by=p.member_id,
        )
    src = az.require("sources", source, "source.configure")
    if not src["enabled"]:
        compare_and_swap(c, "sources", p.org_id, source, src["lock_version"], {"enabled": True})
    tid = uuid4()
    req = {**ds.REQUEST, "one_off_retry": one_off_retry}
    insert(
        c,
        "collection_jobs",
        p.org_id,
        task_id=tid,
        source_id=source,
        connection_id=conn,
        capability_code=ds.CAPABILITY,
        connector_version=ds.VERSION,
        business_code="story_short",
        business_date=shanghai_date(),
        safe_request=req,
        request_sha256=digest(req),
        max_requests=ds.MAX_CALLS,
        max_items=50,
    )
    plan_text = json.dumps(req, sort_keys=True)
    plan_raw = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="manual",
        asset_kind="response",
        submitted_by=p.member_id,
        body_text=plan_text,
        sha256=hashlib.sha256(plan_text.encode()).hexdigest(),
        captured_at=func.clock_timestamp(),
    )
    vals = {
        "id": tid,
        "org_id": p.org_id,
        "kind": ds.KIND,
        "handler_version": ds.VERSION,
        "source_id": source,
        "raw_asset_id": plan_raw,
        "business_code": "story_short",
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_attempts": 1,
        "max_external_calls": ds.MAX_CALLS,
        "idempotency_key": key,
    }
    vals["input_sha256"] = input_digest(vals, handler.freeze(c, vals, az))
    create_task(c, vals, [{"role": "microfilm_plan", "raw_asset_id": plan_raw}])
    return tid, source


def run(engine, p, *, key=None, one_off_retry=False, handler=None):
    handler = handler or Microfilm()
    key = key or "microfilm/" + str(uuid4())
    with engine.begin() as c:
        tid, source = submit(c, p, key, handler, one_off_retry=one_off_retry)
    try:
        state = Runner(engine, {(ds.KIND, ds.VERSION): handler}, lease_seconds=180).run(
            p.org_id, tid
        )
        with engine.begin() as c:
            t = get(c, "tasks", p.org_id, tid)
            manifest_text = c.exec_driver_sql(
                "SELECT r.body_text FROM task_outputs o JOIN raw_assets r ON r.id=o.raw_asset_id AND r.org_id=o.org_id WHERE o.org_id=%s AND o.task_id=%s AND o.role='microfilm_manifest'",
                (p.org_id, tid),
            ).scalar_one_or_none()
            needs_verification = (
                bool(json.loads(manifest_text).get("verification_required"))
                if manifest_text
                else t["safe_error_code"] == "SOURCE_VERIFICATION_REQUIRED"
            )
            return {
                "task_id": str(tid),
                "state": t["state"] if state == "ignored" else state,
                "outcome": t["business_outcome"],
                "error": t["safe_error_code"],
                "verification_required": needs_verification,
            }
    finally:
        with engine.begin() as c:
            src = get(c, "sources", p.org_id, source)
            final_state = c.exec_driver_sql(
                "SELECT state FROM tasks WHERE org_id=%s AND id=%s", (p.org_id, tid)
            ).scalar_one()
            if src["enabled"] and final_state not in ("queued", "running", "cancel_requested"):
                compare_and_swap(
                    c, "sources", p.org_id, source, src["lock_version"], {"enabled": False}
                )
