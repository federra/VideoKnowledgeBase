"""Only the zero-cost local handler is registered at S05.4; no provider fallback."""

import hashlib
from time import monotonic
from uuid import UUID

from app.security.storage import audit
from app.tasks.service import TaskError


class FileVerify:
    action = "content.write"

    def __init__(self, store=None):
        self.store = store

    def freeze(self, c, task, az):
        if task["max_external_calls"] != 0:
            raise TaskError("INVALID_INPUT")
        az.require("works", task["work_id"], self.action)
        f = az.file(task["file_id"], ("works", task["work_id"]))
        return {
            "org": str(task["org_id"]),
            "file": str(f["id"]),
            "work": str(task["work_id"]),
            "sha256": f["sha256"],
            "byte_size": f["byte_size"],
            "media_type": f["media_type"],
        }

    def execute(self, payload, checkpoint):
        from app.storage.http import get_store

        store = self.store or get_store()
        sha, size, started = hashlib.sha256(), 0, monotonic()
        try:
            with store.open(UUID(payload["org"]), UUID(payload["file"])) as stream:
                checkpoint()
                while data := stream.read(65536):
                    sha.update(data)
                    size += len(data)
                    if size > payload["byte_size"]:
                        raise TaskError("INVALID_INPUT")
                    if monotonic() - started > 40:
                        raise TaskError("TIMEOUT")
                    checkpoint()
        except OSError:
            raise TaskError("INVALID_INPUT") from None
        if size != payload["byte_size"] or sha.hexdigest() != payload["sha256"]:
            raise TaskError("INVALID_INPUT")
        return {"sha256": sha.hexdigest(), "byte_size": size}

    def publish(self, c, task, result):
        f = (
            c.exec_driver_sql(
                "SELECT sha256,byte_size FROM file_objects WHERE org_id=%s AND id=%s",
                (task["org_id"], task["file_id"]),
            )
            .mappings()
            .one()
        )
        if dict(f) != result:
            raise TaskError("INVALID_INPUT")
        # File verification produces an audit fact, not an invented analysis/report.
        audit(
            c, task["org_id"], task["execution_authorized_by"], "file.verified", "task", task["id"]
        )


def registry():
    from app.collection.handler import Collect
    from app.collection.schedule import KnowledgeIntake
    from app.connectors.redfox import VERSION, RedFox
    from app.core.config import settings
    from app.knowledge.tasks import KnowledgeTask
    from app.processing.research import Parse
    from app.research.analysis_task import Analyze

    return {
        **{("knowledge." + p, "2"): KnowledgeTask(p) for p in ("extract", "review")},
        ("research.parse", "1"): Parse(),
        **{
            ("research." + purpose, "2"): Analyze(purpose)
            for purpose in ("decompose", "evaluate", "predict")
        },
        ("file.verify", "1"): FileVerify(),
        ("collection.knowledge-intake", "1"): KnowledgeIntake(),
        ("collect.redfox", VERSION): Collect(
            RedFox(
                lambda: (
                    settings.redfox_api_key.get_secret_value() if settings.redfox_api_key else None
                )
            )
        ),
    }
