"""Durable refresh batches reuse frozen tasks, HTTP receipts and append-only audit facts."""

import hashlib
import json
from uuid import UUID, uuid4

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import refresh
from app.security.storage import audit, receipt
from app.tasks.service import input_digest

KIND = "intelligence.refresh"
VERSION = "1"
CHANNELS = {
    "hongguo": "红果",
    "tikhub": "TikHub",
    "fanqie": "番茄",
    "qidian": "起点",
    "qimao": "七猫",
    "creators": "博主",
    "microfilm": "抖音微电影",
}
ACTIONS = ("source.configure", "collection.run", "content.read", "evidence.read", "task.read")
CAPS = (
    "douyin.search.microfilm",
    "hongguo.board",
    "douyin.series.hot",
    "novel.fanqie.catalog",
    "novel.fanqie.board",
    "novel.qidian.board",
    "novel.qimao.board",
)


def authorize(c, p, business):
    refresh(c, p)
    az = Authorizer(c, p)
    if not all(az.allowed(a, {("org", str(p.org_id)), ("business", business)}) for a in ACTIONS):
        raise Denied("ACCESS_DENIED")
    return az


def event(c, task, channel, **details):
    c.execute(
        metadata.tables["audit_events"]
        .insert()
        .values(
            id=uuid4(),
            org_id=task["org_id"],
            actor_member_id=task["requested_by"],
            action_code="intelligence.refresh.progress",
            target_kind="task",
            target_id=task["id"],
            request_id=str(uuid4()),
            safe_details={"code": channel, **details},
        )
    )


def publish_channel(c, task, channel):
    c.execute(
        metadata.tables["audit_events"]
        .insert()
        .values(
            id=uuid4(),
            org_id=task["org_id"],
            actor_member_id=task["requested_by"],
            action_code="intelligence.refresh.published",
            target_kind="task",
            target_id=task["id"],
            request_id=str(uuid4()),
            safe_details={"code": channel},
        )
    )


def latest(c, p, business, task_id=None):
    authorize(c, p, business)
    task = (
        c.exec_driver_sql(
            "SELECT * FROM tasks WHERE org_id=%s AND kind IN (%s,'intelligence.refresh.resume') AND business_code=%s "
            + ("AND id=%s " if task_id else "")
            + "ORDER BY created_at DESC,id DESC LIMIT 1",
            (p.org_id, KIND, business, *((task_id,) if task_id else ())),
        )
        .mappings()
        .one_or_none()
    )
    if not task:
        return {
            "task_id": None,
            "business_code": business,
            "business_date": shanghai_date(),
            "state": "idle",
            "channels": [],
        }
    raw = row(c, "raw_assets", p.org_id, task["raw_asset_id"])
    manifest = json.loads(raw["body_text"])
    day = manifest["day"]
    facts = (
        c.exec_driver_sql(
            "SELECT DISTINCT ON(safe_details->>'code') safe_details FROM audit_events WHERE org_id=%s AND target_id=%s AND action_code='intelligence.refresh.progress' ORDER BY safe_details->>'code',occurred_at DESC,id DESC",
            (p.org_id, task["id"]),
        )
        .scalars()
        .all()
    )
    states = {x["code"]: x for x in facts}
    from app.intelligence.refresh_worker import channel_names

    executed_channels = set(channel_names(manifest))
    channels = [
        dict(
            name=v,
            **states.get(
                k, {"code": k, "state": "queued", "completed": 0, "total": 0, "message": "等待采集"}
            ),
        )
        for k, v in CHANNELS.items()
        if k in executed_channels
        and (not manifest.get("creators_only") or k == "creators")
        and (k != "creators" or manifest.get("creators"))
        and (k != "microfilm" or business == "story_short")
    ]
    # Strip duplicate code from audit details before merging the public shape.
    state = task["state"]
    if state == "succeeded":
        state = (
            "completed"
            if all(x["state"] == "succeeded" for x in channels)
            else "partial"
            if any(x["state"] in ("succeeded", "partial") for x in channels)
            else "failed"
        )
    elif state not in ("queued", "running"):
        state = "failed"
        for ch in channels:
            if ch["state"] in ("queued", "running"):
                ch.update(state="failed", message="任务中断或权限变化；未自动重试，旧数据保留")
    return {
        "task_id": str(task["id"]),
        "business_code": business,
        "business_date": day,
        "state": state,
        "channels": channels,
    }


def start(c, p, business, key, *, creators_only=False):
    az = authorize(c, p, business)

    def perform():
        active = (
            c.exec_driver_sql(
                "SELECT id,business_code FROM tasks WHERE org_id=%s AND kind IN (%s,'intelligence.refresh.resume') AND state IN ('queued','running','cancel_requested') ORDER BY created_at LIMIT 1",
                (p.org_id, KIND),
            )
            .mappings()
            .one_or_none()
        )
        if active:
            if active["business_code"] != business:
                raise Denied("VERSION_CONFLICT")
            if creators_only:
                running = row(c, "tasks", p.org_id, active["id"])
                frozen = json.loads(row(c, "raw_assets", p.org_id, running["raw_asset_id"])["body_text"])
                if not frozen.get("creators_only"):
                    raise Denied("VERSION_CONFLICT")
            return {"task_id": str(active["id"])}
        specs = []
        for job in c.exec_driver_sql(
            "SELECT * FROM (SELECT DISTINCT ON(j.source_id) j.* FROM collection_jobs j JOIN sources s ON s.org_id=j.org_id AND s.id=j.source_id WHERE j.org_id=%s AND j.business_code=%s AND j.capability_code=ANY(%s) AND s.target_kind='board' ORDER BY j.source_id,j.created_at DESC,j.id DESC) recent ORDER BY created_at,id",
            (p.org_id, business, [] if creators_only else list(CAPS)),
        ).mappings():
            az.require("sources", job["source_id"], "source.configure")
            az.require("sources", job["source_id"], "collection.run")
            specs.append(
                {
                    k: str(job[k]) if k in ("source_id", "connection_id") else job[k]
                    for k in (
                        "source_id",
                        "connection_id",
                        "capability_code",
                        "connector_version",
                        "safe_request",
                        "max_items",
                    )
                }
            )
        from app.intelligence.creators import current

        config_raw, creators = current(c, p.org_id, business)
        manifest = {
            "business": business,
            "day": str(shanghai_date()),
            "specs": specs,
            "creators": creators,
            "creator_config_raw": str(config_raw) if config_raw else None,
            "creators_only": creators_only,
        }
        if business == "story_short":
            from app.connectors.douyin_posts import window
            manifest["creator_window"] = window(c.exec_driver_sql("SELECT clock_timestamp()").scalar_one())
        unique = {}
        for value in specs:
            request = value["safe_request"]
            code = request.get("code") or request.get("board") or value["capability_code"]
            unique[(value["capability_code"], code)] = value
        manifest["specs"] = list(unique.values())
        text = json.dumps(manifest, sort_keys=True)
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
            "business_code": business,
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": 0,
            "idempotency_key": str(p.member_id) + ":" + key,
        }
        values["input_sha256"] = input_digest(values, manifest)
        tid, _ = create_task(
            c,
            values,
            [{"role": "refresh_plan", "raw_asset_id": raw}]
            + ([{"role": "creator_config", "raw_asset_id": config_raw}] if config_raw else []),
        )
        audit(c, p.org_id, p.member_id, "intelligence.refresh.requested", "task", tid)
        return {"task_id": str(tid)}

    result = receipt(c, p, "refreshIntelligence", key, {"business_code": business}, perform)
    return latest(c, p, business, UUID(result["task_id"]))
