"""Qidian-only explicit capture; reuse budgets, fences and immutable publication."""

from uuid import UUID

from app.collection.handler import publish_batch
from app.collection.novels import NovelCollect
from app.collection.service import get
from app.connectors.qidian_mobile import METHOD, discover, normalize
from app.core.models import metadata
from app.intelligence.service import shanghai_date
from app.tasks.service import TaskError


class QidianCollect(NovelCollect):
    def freeze(self, c, task, az):
        value = super().freeze(c, task, az)
        request = value["request"]
        if (
            request.get("platform") != "qidian"
            or request.get("method") != METHOD
            or request.get("gender") not in ("male", "female")
            or request.get("code") != f"qidian:mobile:{request['gender']}:{request['rank_type']}"
        ):
            raise TaskError("INVALID_INPUT")
        return value

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
        if job["capability_code"] == "novel.qidian.catalog":
            discover(raw["body_text"], job["safe_request"]["gender"])
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
        elif job["capability_code"] == "novel.qidian.board":
            publish_batch(c, task, raw, job, normalize(job["safe_request"], raw["body_text"]))
        else:
            raise TaskError("INVALID_INPUT")
