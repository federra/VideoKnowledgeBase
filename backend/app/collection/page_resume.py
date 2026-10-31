"""Explicit same-day continuation using immutable, genuinely successful API pages.

Reused pages remain attached to their original calls. New tasks freeze typed raw
references and their SHA values; only missing requests consume the new budget.
"""

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func

from app.collection.service import get, insert
from app.core.repository import compare_and_swap, create_task
from app.intelligence.service import shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.tasks.service import Runner, TaskError, input_digest

KINDS = {
    "douyin.creator.posts": "collect.creator-posts.resume",
    "douyin.search.microfilm": "collect.microfilm.resume",
}


def _job(c, org, ident):
    j = get(c, "collection_jobs", org, ident)
    if j is None:
        raise TaskError("INVALID_INPUT")
    return j


def _manifest(c, task, az):
    ident = task.get("_resume_manifest")
    if ident is None:
        ident = c.exec_driver_sql(
            "SELECT raw_asset_id FROM task_inputs WHERE org_id=%s AND task_id=%s AND role='collection_resume_manifest'",
            (task["org_id"], task["id"]),
        ).scalar_one_or_none()
    if not ident:
        raise TaskError("INVALID_INPUT")
    raw = az.read("raw_assets", ident)
    if (
        raw["origin"] != "manual"
        or raw["submitted_by"] != task["requested_by"]
        or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
    ):
        raise TaskError("INVALID_INPUT")
    return json.loads(raw["body_text"])


def reuse_rows(c, org, job, az=None):
    """Return only sealed typed references; never make copies of provider raws."""
    rows = (
        c.exec_driver_sql(
            "SELECT r.*,cc.sequence_no,cc.outcome,cc.http_status,cc.request_sha256 AS page_request_sha256 FROM task_inputs i JOIN raw_assets r ON r.org_id=i.org_id AND r.id=i.raw_asset_id JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id WHERE i.org_id=%s AND i.task_id=%s AND i.role='collection_page_reuse' ORDER BY i.position",
            (org, job["task_id"]),
        )
        .mappings()
        .all()
    )
    for raw in rows:
        if az:
            az.read("raw_assets", raw["id"])
    return rows


def _checked(c, org, job, ids, az):
    from app.collection.microfilm import comment_rows
    from app.connectors import douyin_posts as dp
    from app.connectors import douyin_search as ds

    if job["business_date"] != shanghai_date() or job["business_code"] != "story_short":
        raise TaskError("DATE_WINDOW_MISMATCH")
    if not ids or len(ids) != len(set(ids)):
        raise TaskError("INVALID_INPUT")
    raws = []
    for ident in ids:
        raw = az.read("raw_assets", UUID(str(ident)))
        original = _job(c, org, raw["collection_job_id"]) if raw["collection_job_id"] else None
        call = (
            get(c, "collection_calls", org, raw["collection_call_id"])
            if raw["collection_call_id"]
            else None
        )
        original_task = get(c, "tasks", org, original["task_id"]) if original else None
        if (
            not original
            or not call
            or not original_task
            or original_task["state"] not in ("failed", "succeeded")
            or original_task["kind"]
            not in (
                KINDS.get(job["capability_code"]),
                KINDS.get(job["capability_code"], "").removesuffix(".resume"),
            )
            or original_task["handler_version"] != job["connector_version"]
            or raw["origin"] != "api"
            or call["job_id"] != original["id"]
            or call["outcome"] != "success"
            or call["http_status"] != 200
            or raw["sha256"] != hashlib.sha256(raw["body_text"].encode()).hexdigest()
            or shanghai_date(raw["captured_at"]) != job["business_date"]
            or any(
                original[k] != job[k]
                for k in (
                    "source_id",
                    "connection_id",
                    "business_code",
                    "business_date",
                    "capability_code",
                    "connector_version",
                    "safe_request",
                    "request_sha256",
                    "max_requests",
                    "max_items",
                )
            )
        ):
            raise TaskError("INVALID_INPUT")
        raws.append(
            {
                **raw,
                "page_request_sha256": call["request_sha256"],
                "outcome": "success",
                "http_status": 200,
                "sequence_no": call["sequence_no"],
            }
        )
    seen, pages, comments, cursor = set(), [], {}, 0
    for raw in raws:
        value = json.loads(raw["body_text"])
        key = raw["page_request_sha256"]
        if key in seen:
            raise TaskError("INVALID_INPUT")
        seen.add(key)
        if job["capability_code"] == dp.CAPABILITY:
            if key != digest(
                {"sec_user_id": job["safe_request"]["sec_user_id"], "max_cursor": cursor}
            ):
                raise TaskError("INVALID_INPUT")
            if pages and dp.complete(pages[-1][1], job["safe_request"]["window"]):
                raise TaskError("INVALID_INPUT")
            dp.normalize_page(value, job["safe_request"]["sec_user_id"], job["safe_request"]["uid"])
            next_cursor = value["max_cursor"]
            if len(pages) >= dp.MAX_PAGES or (
                not dp.complete(value, job["safe_request"]["window"])
                and (
                    next_cursor == 0
                    or (cursor and next_cursor >= cursor)
                    or next_cursor in {p[0] for p in pages}
                )
            ):
                raise TaskError("INVALID_INPUT")
            pages.append((cursor, value))
            cursor = next_cursor
        elif value.get("kind") == "search":
            requested = int(value["parameters"]["offset"])
            search_id = (pages[-1]["body"].get("extra") or {}).get("logid", "") if pages else ""
            if key != digest(
                {"kind": "search", "target": "微电影", "cursor": requested, "search_id": search_id}
            ):
                raise TaskError("INVALID_INPUT")
            pages.append(value)
            ds.combine(pages)
        elif value.get("kind") == "comments":
            aid = value["parameters"]["aweme_id"]
            requested = int(value["parameters"].get("cursor", 0))
            if key != digest(
                {"kind": "comments", "target": aid, "cursor": requested, "search_id": ""}
            ):
                raise TaskError("INVALID_INPUT")
            comments.setdefault(aid, []).append((raw, value))
        else:
            raise TaskError("INVALID_INPUT")
    if not pages:
        raise TaskError("INVALID_INPUT")
    if job["capability_code"] == ds.CAPABILITY:
        batch, _ = ds.combine(pages)
        aids = {r["platform_content_id"] for r in batch.records}
        for aid, values in comments.items():
            requested, total, ended = 0, set(), False
            for _, value in values:
                if ended or int(value["parameters"].get("cursor", 0)) != requested:
                    raise TaskError("INVALID_INPUT")
                for row in ds.comment_page(value, aid):
                    total.add(row["platform_comment_id"])
                body = value["body"]
                ended = len(total) >= 15 or body.get("has_more") == 0
                requested = body.get("cursor")
                if not ended and (
                    type(requested) is not int
                    or requested <= int(value["parameters"].get("cursor", 0))
                    or requested >= 15
                ):
                    raise TaskError("INVALID_INPUT")
            if aid not in aids:
                raise TaskError("INVALID_INPUT")
            comment_rows(values, aid)
    return raws


class ResumeMixin:
    def freeze(self, c, task, az):
        payload = super().freeze(c, task, az)
        job = _job(c, task["org_id"], UUID(payload["job_id"]))
        manifest = _manifest(c, task, az)
        parent = _job(c, task["org_id"], UUID(manifest["original_job"]))
        original_task = get(c, "tasks", task["org_id"], parent["task_id"])
        if (
            task["kind"] != KINDS.get(job["capability_code"])
            or original_task["state"] not in ("failed", "succeeded")
            or any(
                parent[k] != job[k]
                for k in (
                    "source_id",
                    "connection_id",
                    "business_code",
                    "business_date",
                    "capability_code",
                    "connector_version",
                    "safe_request",
                    "request_sha256",
                    "max_requests",
                    "max_items",
                )
            )
        ):
            raise TaskError("INVALID_INPUT")
        raws = _checked(c, task["org_id"], job, [r["id"] for r in manifest["pages"]], az)
        if [{"id": str(r["id"]), "sha256": r["sha256"]} for r in raws] != manifest["pages"]:
            raise TaskError("INVALID_INPUT")
        if "_resume_manifest" not in task and [
            r["id"] for r in reuse_rows(c, task["org_id"], job)
        ] != [r["id"] for r in raws]:
            raise TaskError("INVALID_INPUT")
        payload["reused_pages"] = [
            {
                "raw_asset_id": str(r["id"]),
                "sha256": r["sha256"],
                "request_sha256": r["page_request_sha256"],
                "value": json.loads(r["body_text"]),
            }
            for r in raws
        ]
        return payload


def _handler(capability, connector=None, connector_factory=None):
    from app.collection.creator_posts import CreatorPosts
    from app.collection.microfilm import Microfilm

    if capability == "douyin.search.microfilm":

        class MicrofilmResume(ResumeMixin, Microfilm):
            pass

        return MicrofilmResume(connector_factory)
    if capability == "douyin.creator.posts":

        class CreatorPostsResume(ResumeMixin, CreatorPosts):
            pass

        if connector is None:
            raise TaskError("INVALID_INPUT")
        return CreatorPostsResume(connector)
    raise TaskError("INVALID_INPUT")


def submit_resume(
    c, p, original_job_id, *, key, raw_ids=None, connector=None, connector_factory=None
):
    refresh(c, p)
    az = Authorizer(c, p)
    parent = _job(c, p.org_id, UUID(str(original_job_id)))
    handler = _handler(parent["capability_code"], connector, connector_factory)
    src = az.require("sources", parent["source_id"], "source.configure")
    for action in ("collection.run", "content.read", "evidence.read", "task.read"):
        if not az.allowed(action, {("org", str(p.org_id)), ("business", "story_short")}):
            raise TaskError("ACCESS_REVOKED")
    existing = c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND kind=%s AND idempotency_key=%s",
        (p.org_id, KINDS[parent["capability_code"]], key),
    ).scalar_one_or_none()
    if existing:
        existing_task = get(c, "tasks", p.org_id, existing)
        m = _manifest(c, existing_task, az)
        if (
            m["original_job"] != str(parent["id"])
            or raw_ids is not None
            and [r["id"] for r in m["pages"]] != [str(r) for r in raw_ids]
        ):
            raise TaskError("IDEMPOTENCY_CONFLICT")
        return existing, parent["source_id"], handler
    if raw_ids is None:
        prior = list(reuse_rows(c, p.org_id, parent))
        rows = (
            c.exec_driver_sql(
                "SELECT r.id,cc.request_sha256 FROM raw_assets r JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id WHERE r.org_id=%s AND r.collection_job_id=%s AND cc.outcome='success' AND cc.http_status=200 ORDER BY cc.sequence_no",
                (p.org_id, parent["id"]),
            )
            .mappings()
            .all()
        )
        raw_ids = [r["id"] for r in prior] + [r["id"] for r in rows]
        if parent["capability_code"] == "douyin.search.microfilm":
            # The current manifest, rather than all physical comment rows, defines
            # the successful sample to continue. Its raw IDs remain independently checked.
            latest = c.exec_driver_sql(
                "SELECT r.body_text FROM collection_jobs j JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id JOIN task_outputs o ON o.org_id=t.org_id AND o.task_id=t.id AND o.role='microfilm_manifest' JOIN raw_assets r ON r.org_id=o.org_id AND r.id=o.raw_asset_id WHERE j.org_id=%s AND j.source_id=%s AND j.business_date=%s AND j.safe_request=%s::jsonb AND t.state='succeeded' ORDER BY j.created_at DESC,j.id DESC LIMIT 1",
                (
                    p.org_id,
                    parent["source_id"],
                    parent["business_date"],
                    json.dumps(parent["safe_request"]),
                ),
            ).scalar_one_or_none()
            if latest:
                comments = json.loads(latest).get("comments", {})
                retained = []
                for ident in raw_ids:
                    value = json.loads(get(c, "raw_assets", p.org_id, ident)["body_text"])
                    if (
                        value.get("kind") != "comments"
                        or value.get("parameters", {}).get("aweme_id") not in comments
                    ):
                        retained.append(ident)
                raw_ids = retained
                current = set(raw_ids)
                for ids in comments.values():
                    for ident in ids:
                        ident = UUID(ident)
                        if ident not in current:
                            current.add(ident)
                            raw_ids.append(ident)
    raws = _checked(c, p.org_id, parent, [str(i) for i in raw_ids], az)
    if not src["enabled"]:
        compare_and_swap(c, "sources", p.org_id, src["id"], src["lock_version"], {"enabled": True})
    tid = uuid4()
    jobvals = {
        k: parent[k]
        for k in (
            "source_id",
            "connection_id",
            "capability_code",
            "connector_version",
            "business_code",
            "business_date",
            "safe_request",
            "request_sha256",
            "max_requests",
            "max_items",
        )
    }
    insert(c, "collection_jobs", p.org_id, task_id=tid, **jobvals)
    req_text = json.dumps(parent["safe_request"], sort_keys=True)
    plan = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="manual",
        asset_kind="response",
        submitted_by=p.member_id,
        body_text=req_text,
        sha256=hashlib.sha256(req_text.encode()).hexdigest(),
        captured_at=func.clock_timestamp(),
    )
    manifest_text = json.dumps(
        {
            "original_job": str(parent["id"]),
            "pages": [{"id": str(r["id"]), "sha256": r["sha256"]} for r in raws],
        },
        sort_keys=True,
    )
    manifest = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="manual",
        asset_kind="response",
        submitted_by=p.member_id,
        body_text=manifest_text,
        sha256=hashlib.sha256(manifest_text.encode()).hexdigest(),
        captured_at=func.clock_timestamp(),
    )
    vals = {
        "id": tid,
        "org_id": p.org_id,
        "kind": KINDS[parent["capability_code"]],
        "handler_version": parent["connector_version"],
        "source_id": src["id"],
        "raw_asset_id": plan,
        "business_code": "story_short",
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_attempts": 1,
        "max_external_calls": parent["max_requests"],
        "idempotency_key": key,
    }
    vals["input_sha256"] = input_digest(
        vals, handler.freeze(c, {**vals, "_resume_manifest": manifest}, az)
    )
    create_task(
        c,
        vals,
        [
            {"role": "collection_resume_plan", "raw_asset_id": plan},
            {"role": "collection_resume_manifest", "raw_asset_id": manifest},
        ]
        + [{"role": "collection_page_reuse", "raw_asset_id": r["id"]} for r in raws],
    )
    return tid, src["id"], handler


def start_resume(
    engine, p, original_job_id, *, key, raw_ids=None, connector=None, connector_factory=None
):
    with engine.begin() as c:
        tid, source, handler = submit_resume(
            c,
            p,
            original_job_id,
            key=key,
            raw_ids=raw_ids,
            connector=connector,
            connector_factory=connector_factory,
        )
    try:
        with engine.connect() as c:
            task = get(c, "tasks", p.org_id, tid)
        Runner(engine, {(task["kind"], task["handler_version"]): handler}, lease_seconds=180).run(
            p.org_id, tid
        )
        with engine.begin() as c:
            t = get(c, "tasks", p.org_id, tid)
            return {
                "task_id": str(tid),
                "state": t["state"],
                "outcome": t["business_outcome"],
                "error": t["safe_error_code"],
            }
    finally:
        with engine.begin() as c:
            src = get(c, "sources", p.org_id, source)
            t = get(c, "tasks", p.org_id, tid)
            if src["enabled"] and t["state"] not in ("queued", "running", "cancel_requested"):
                compare_and_swap(
                    c, "sources", p.org_id, source, src["lock_version"], {"enabled": False}
                )
