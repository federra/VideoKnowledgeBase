"""Qimao uses the existing one-request novel task and immutable evidence pipeline."""

from uuid import UUID

from app.collection.handler import publish_batch
from app.collection.novels import NovelCollect
from app.collection.service import get
from app.connectors.qimao import CAPABILITY, normalize, validate_board
from app.intelligence.service import shanghai_date
from app.tasks.service import TaskError


class QimaoCollect(NovelCollect):
    def __init__(self, connector):
        super().__init__(connector, min_interval=10)

    def freeze(self, c, task, az):
        value = super().freeze(c, task, az)
        if value["capability"] != CAPABILITY:
            raise TaskError("INVALID_INPUT")
        validate_board(value["request"])
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
            or job["capability_code"] != CAPABILITY
            or shanghai_date(raw["captured_at"]) != job["business_date"]
        ):
            raise TaskError("INVALID_INPUT")
        publish_batch(c, task, raw, job, normalize(job["safe_request"], raw["body_text"]))
