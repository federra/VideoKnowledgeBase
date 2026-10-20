"""Explicit one-shot public novel collection. No schedules or automatic retries."""

import json
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.collection.handler import Collect, publish_batch
from app.collection.service import get, insert
from app.connectors.novels import (
    CAPABILITIES,
    CATALOG,
    QCATALOG,
    VERSION,
    catalog,
    normalize,
    qidian_catalog,
)
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, receipt
from app.tasks.service import TaskError, input_digest


class NovelCollect(Collect):
    def freeze(self, c, task, az):
        org = task["org_id"]
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, task["id"])
            )
            .mappings()
            .one()
        )
        source = az.require("sources", job["source_id"], self.action)
        conn = get(c, "provider_connections", org, job["connection_id"])
        request = job["safe_request"]
        platform = request.get("platform")
        expected = (
            ("novel." + str(platform) + ".catalog")
            if request.get("rank_type") == "catalog"
            else ("novel." + str(platform) + ".board")
        )
        if (
            platform not in ("fanqie", "qidian")
            or source["platform_code"] != platform
            or source["board_code"] != request.get("code")
            or source["business_code"] != task["business_code"]
            or source["target_kind"] != "board"
            or not source["enabled"]
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "novel_public"
            or conn["secret_ref"] != "PUBLIC_NOVEL_NO_SECRET"
            or job["capability_code"] not in CAPABILITIES
            or job["capability_code"] != expected
            or job["connector_version"] != VERSION
            or job["plan_id"] is not None
            or digest(request) != job["request_sha256"]
            or job["max_requests"] != 1
            or job["max_items"] != 30
            or task["max_external_calls"] != 1
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "source_version": source["lock_version"],
            "connection_version": conn["lock_version"],
            "request": request,
            "capability": job["capability_code"],
            "maximum": 30,
            "business_date": str(job["business_date"]),
        }

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
            or shanghai_date(raw["captured_at"]) != job["business_date"]
        ):
            raise TaskError("INVALID_INPUT")
        cap = job["capability_code"]
        if cap in (CATALOG, QCATALOG):
            (catalog if cap == CATALOG else qidian_catalog)(raw["body_text"])
            c.execute(
                metadata.tables["task_outputs"]
                .insert()
                .values(
                    org_id=org,
                    task_id=task["id"],
                    position=0,
                    role="novel_catalog_response",
                    raw_asset_id=raw["id"],
                )
            )
        elif cap == "novel.fanqie.board":
            publish_batch(
                c,
                task,
                raw,
                job,
                normalize(
                    job["safe_request"],
                    json.loads(raw["body_text"]),
                    decoder=self.connector.decoder,
                ),
            )
        else:
            raise TaskError("SOURCE_UNAVAILABLE")
        audit(
            c,
            org,
            task["execution_authorized_by"],
            "novel.response_captured",
            "raw_asset",
            raw["id"],
        )


def submit(c, p, board, handler, *, business="motion_comic", external_calls=1, inputs=()):
    refresh(c, p)
    az = Authorizer(c, p)
    for action in ("source.configure", "collection.run"):
        if not az.allowed(action, {("org", str(p.org_id)), ("business", business)}):
            raise TaskError("ACCESS_DENIED")
    platform = board.get("platform")
    code = board.get("code")
    day = shanghai_date()
    if (
        platform not in ("fanqie", "qidian")
        or not isinstance(code, str)
        or not code.startswith(platform + ":")
    ):
        raise TaskError("INVALID_INPUT")
    cap = "novel." + platform + (".catalog" if board.get("rank_type") == "catalog" else ".board")

    def perform():
        # Per-source/day budget survives new idempotency keys and process restarts.
        old = (
            c.exec_driver_sql(
                "SELECT j.task_id,j.id job_id,j.source_id FROM collection_jobs j JOIN sources s ON s.id=j.source_id AND s.org_id=j.org_id WHERE j.org_id=%s AND j.business_code=%s AND j.business_date=%s AND s.platform_code=%s AND s.board_code=%s ORDER BY j.created_at DESC LIMIT 1",
                (p.org_id, business, day, platform, code),
            )
            .mappings()
            .one_or_none()
        )
        if old:
            return {k: str(old[k]) for k in ("task_id", "job_id", "source_id")}
        conn = (
            c.exec_driver_sql(
                "SELECT * FROM provider_connections WHERE org_id=%s AND provider_code='novel_public' ORDER BY created_at,id LIMIT 1",
                (p.org_id,),
            )
            .mappings()
            .one_or_none()
        )
        if conn and (not conn["enabled"] or conn["secret_ref"] != "PUBLIC_NOVEL_NO_SECRET"):
            raise TaskError("SOURCE_UNAVAILABLE")
        connection = (
            conn["id"]
            if conn
            else insert(
                c,
                "provider_connections",
                p.org_id,
                name="小说官方公开榜单",
                provider_code="novel_public",
                secret_ref="PUBLIC_NOVEL_NO_SECRET",
                enabled=True,
            )
        )
        name = (
            ("番茄小说" if platform == "fanqie" else "起点中文网") + " · " + board.get("name", code)
        )
        existing = (
            c.exec_driver_sql(
                "SELECT * FROM sources WHERE org_id=%s AND business_code=%s AND platform_code=%s AND board_code=%s ORDER BY created_at,id LIMIT 1",
                (p.org_id, business, platform, code),
            )
            .mappings()
            .one_or_none()
        )
        if existing:
            raise TaskError(
                "SOURCE_UNAVAILABLE"
            )  # Re-arming a paused source is a separate explicit decision.
        source = insert(
            c,
            "sources",
            p.org_id,
            name=name,
            business_code=business,
            platform_code=platform,
            target_kind="board",
            board_code=code,
            enabled=True,
            created_by=p.member_id,
        )
        tid = uuid4()
        job = insert(
            c,
            "collection_jobs",
            p.org_id,
            source_id=source,
            connection_id=connection,
            task_id=tid,
            capability_code=cap,
            connector_version=VERSION,
            business_code=business,
            business_date=day,
            safe_request=board,
            request_sha256=digest(board),
            max_requests=1,
            max_items=30,
        )
        values = {
            "id": tid,
            "org_id": p.org_id,
            "kind": "collect.novels",
            "handler_version": VERSION,
            "source_id": source,
            "business_code": business,
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": external_calls,
            "idempotency_key": str(p.member_id) + ":novel:" + str(day) + ":" + code,
        }
        values["input_sha256"] = input_digest(values, handler.freeze(c, values, az))
        create_task(c, values, inputs)
        return {"task_id": str(tid), "job_id": str(job), "source_id": str(source)}

    return receipt(
        c,
        p,
        "collectNovels",
        str(
            uuid5(
                NAMESPACE_URL,
                str(p.org_id)
                + ":"
                + str(p.member_id)
                + ":"
                + str(day)
                + ":"
                + business
                + ":"
                + code,
            )
        ),
        board,
        perform,
    )
