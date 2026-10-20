"""Deterministic material parsing. No paid or model calls; output is derived evidence."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from app.collection.service import insert
from app.core.models import metadata
from app.tasks.service import TaskError


def parse_text(text):
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 200000
        or any(ord(c) < 32 and c not in "\r\n\t\f" for c in text)
    ):
        raise ValueError("Invalid text")
    return [
        {"number": i, "text": line.removesuffix("\r")}
        for i, line in enumerate(text.split("\n"), 1)
        if line.strip()
    ]


class Parse:
    action = "content.write"

    def __init__(self, store=None):
        self.store = store

    def freeze(self, c, task, az, *, inputs=None):
        inputs = (
            inputs
            if inputs is not None
            else c.exec_driver_sql(
                "SELECT * FROM task_inputs WHERE org_id=%s AND task_id=%s ORDER BY position",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .all()
        )
        if (
            len(inputs) != 1
            or not inputs[0].get("artifact_version_id")
            or task["max_external_calls"] != 0
        ):
            raise TaskError("INVALID_INPUT")
        v = az.require("artifact_versions", inputs[0]["artifact_version_id"], self.action)
        work = az.require("works", v["work_id"], self.action)
        if (
            task["work_id"] != work["id"]
            or task["business_code"] != work["business_code"]
            or not v["sealed_at"]
        ):
            raise TaskError("INVALID_INPUT")
        f = az.read("file_objects", v["file_id"]) if v["file_id"] else None
        return {
            "version_id": str(v["id"]),
            "version_sha256": v["content_sha256"],
            "body_text": v["body_text"],
            "file_id": str(v["file_id"]) if v["file_id"] else None,
            "file_sha256": f["sha256"] if f else None,
            "media_type": f["media_type"] if f else None,
            "byte_size": f["byte_size"] if f else None,
            "parser_version": 1,
        }

    def execute(self, payload, checkpoint):
        checkpoint()
        text = payload["body_text"]
        media = "text"
        missing = []
        duration = None
        if text is None:
            from app.storage.http import get_store

            store = self.store or get_store()
            # Store open uses the org-scoped file identity; supplied by execute_ticket.
            with store.open(UUID(payload["org_id"]), UUID(payload["file_id"])) as stream:
                body = stream.read(64 * 1024 * 1024 + 1)
            if (
                len(body) > 64 * 1024 * 1024
                or hashlib.sha256(body).hexdigest() != payload["file_sha256"]
            ):
                raise TaskError("INVALID_INPUT")
            if payload["media_type"] == "text/plain":
                try:
                    text = body.decode("utf-8-sig")
                except UnicodeError:
                    raise TaskError("INVALID_RESPONSE") from None
            elif payload["media_type"] in ("video/mp4", "audio/wav"):
                from app.processing.media import probe_media

                info = probe_media(body, payload["media_type"])
                duration = info["duration_ms"]
                media = info["media_kind"]
                missing = ["未配置且未验收音视频转写，未取得可定位正文"]
            else:
                raise TaskError("INSUFFICIENT_MATERIAL")
        try:
            paragraphs = parse_text(text) if text is not None else []
        except ValueError:
            raise TaskError("INVALID_RESPONSE") from None
        checkpoint()
        return {
            "text": text,
            "paragraphs": paragraphs,
            "media_kind": media,
            "duration_ms": duration,
            "missing_inputs": missing,
            "result_state": "completed" if paragraphs else "insufficient_evidence",
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        return self.execute({**ticket.payload, "org_id": str(ticket.org)}, checkpoint)

    def publish(self, c, task, result):
        from app.security.authorization import Authorizer
        from app.security.sessions import MemberPrincipal

        frozen = self.freeze(
            c, task, Authorizer(c, MemberPrincipal(task["org_id"], task["execution_authorized_by"]))
        )
        if result["text"] is not None and parse_text(result["text"]) != result["paragraphs"]:
            raise TaskError("INVALID_RESPONSE")
        text_raw = None
        paragraphs = []
        if result["text"] is not None:
            text_raw = insert(
                c,
                "raw_assets",
                task["org_id"],
                origin="processing",
                asset_kind="text",
                processing_task_id=task["id"],
                parent_artifact_version_id=UUID(frozen["version_id"]),
                body_text=result["text"],
                sha256=hashlib.sha256(result["text"].encode()).hexdigest(),
                captured_at=datetime.now(UTC),
            )
            for para in result["paragraphs"]:
                eid = insert(
                    c,
                    "evidence_refs",
                    task["org_id"],
                    raw_asset_id=text_raw,
                    locator_kind="paragraph",
                    paragraph_no=para["number"],
                    quoted_text=para["text"],
                )
                paragraphs.append({**para, "evidence_id": str(eid)})
        manifest = {
            k: result[k] for k in ("media_kind", "duration_ms", "missing_inputs", "result_state")
        }
        manifest.update(
            schema_version=1,
            parser_version=1,
            artifact_version_id=frozen["version_id"],
            text_raw_id=str(text_raw) if text_raw else None,
            paragraphs=paragraphs,
        )
        body = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        raw = insert(
            c,
            "raw_assets",
            task["org_id"],
            origin="processing",
            asset_kind="response",
            processing_task_id=task["id"],
            parent_artifact_version_id=UUID(frozen["version_id"]),
            body_text=body,
            sha256=hashlib.sha256(body.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"],
                task_id=task["id"],
                position=0,
                role="parsed_document",
                raw_asset_id=raw,
            )
        )
