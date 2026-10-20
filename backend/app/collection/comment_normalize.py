"""Normalize only the verified TikHub first-page shape; never request another page."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

from app.collection.service import get, insert
from app.connectors.redfox import number
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import authorized, row, shanghai_date
from app.security.authorization import Authorizer
from app.security.sessions import refresh
from app.tasks.service import TaskError, input_digest


def normalize_comments(body, target):
    if not isinstance(body, dict) or body.get("code") != 200:
        raise ValueError("INVALID_RESPONSE")
    data = body.get("data")
    if (
        not isinstance(data, dict)
        or data.get("status_code") != 0
        or not isinstance(data.get("comments"), list)
    ):
        raise ValueError("INVALID_RESPONSE")
    rows = []
    seen = {}
    for position, item in enumerate(data["comments"][:20]):
        if not isinstance(item, dict) or item.get("aweme_id") != target:
            raise ValueError("INVALID_RESPONSE")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        cid = item.get("cid")
        if not isinstance(cid, str) or not cid.strip():
            raise ValueError("INVALID_RESPONSE")
        posted = item.get("create_time")
        moment = None
        if posted is not None:
            if type(posted) is not int or not 0 <= posted <= 253402300799:
                raise ValueError("INVALID_RESPONSE")
            moment = datetime.fromtimestamp(posted, UTC)
        user = item.get("user")
        name = user.get("nickname") if isinstance(user, dict) else None
        if name is not None and not isinstance(name, str):
            raise ValueError("INVALID_RESPONSE")
        row = {
            "platform_comment_id": cid,
            "body_text": text,
            "username": name or None,
            "like_count": number(item.get("digg_count")),
            "posted_at_raw": str(posted) if posted is not None else None,
            "posted_at": moment,
            "posted_timezone": "UTC" if moment else None,
            "sample_position": position,
        }
        fingerprint = {k: v for k, v in row.items() if k != "sample_position"}
        if cid in seen:
            if seen[cid] != fingerprint:
                raise ValueError("INVALID_RESPONSE")
            continue
        seen[cid] = fingerprint
        rows.append(row)
    return rows


class NormalizeComments:
    action = "content.write"

    def freeze(self, c, task, az, *, inputs=None):
        inputs = (
            inputs
            if inputs is not None
            else c.exec_driver_sql(
                "SELECT raw_asset_id,snapshot_id FROM task_inputs WHERE org_id=%s AND task_id=%s ORDER BY position",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .all()
        )
        raws = [x["raw_asset_id"] for x in inputs if x["raw_asset_id"]]
        snaps = [x["snapshot_id"] for x in inputs if x["snapshot_id"]]
        if len(inputs) != 2 or len(raws) != 1 or len(snaps) != 1 or task["max_external_calls"] != 0:
            raise TaskError("INVALID_INPUT")
        raw = az.read("raw_assets", raws[0])
        full = row(c, "raw_assets", task["org_id"], raws[0])
        snap = row(c, "intelligence_snapshots", task["org_id"], snaps[0])
        authorized(c, az.p, snap)
        job = get(c, "collection_jobs", task["org_id"], full["collection_job_id"])
        source = az.require("sources", job["source_id"], self.action)
        call = get(c, "collection_calls", task["org_id"], full["collection_call_id"])
        if (
            call["outcome"] != "success"
            or job["capability_code"] != "douyin.comments.capture"
            or job["connector_version"] != "tikhub-comments-capture-v1"
            or job["business_date"] != snap["business_date"]
            or job["business_code"] != snap["business_code"]
            or shanghai_date(full["captured_at"]) != snap["business_date"]
            or task["source_id"] != source["id"]
        ):
            raise TaskError("INVALID_INPUT")
        content = row(c, "external_contents", task["org_id"], source["content_id"])
        match = c.exec_driver_sql(
            "SELECT 1 FROM snapshot_entries e JOIN content_observations o ON o.id=e.content_observation_id AND o.org_id=e.org_id WHERE e.org_id=%s AND e.snapshot_id=%s AND o.content_id=%s",
            (task["org_id"], snap["id"], content["id"]),
        ).first()
        if not match:
            raise TaskError("INVALID_INPUT")
        comments = normalize_comments(json.loads(full["body_text"]), content["platform_content_id"])
        return {
            "raw_id": str(full["id"]),
            "snapshot_id": str(snap["id"]),
            "content_id": str(content["id"]),
            "captured_at": full["captured_at"].isoformat(),
            "raw_sha256": raw["sha256"],
            "comments": [
                {**x, "posted_at": x["posted_at"].isoformat() if x["posted_at"] else None}
                for x in comments
            ],
        }

    def execute(self, payload, checkpoint):
        checkpoint()
        return payload

    def publish(self, c, task, result):
        # Runner has revalidated the identical immutable payload before reaching this transaction.
        for item in result["comments"]:
            values = {
                **item,
                "posted_at": datetime.fromisoformat(item["posted_at"])
                if item["posted_at"]
                else None,
            }
            insert(
                c,
                "comment_evidence",
                task["org_id"],
                id=uuid5(UUID(result["raw_id"]), str(item["sample_position"])),
                raw_asset_id=UUID(result["raw_id"]),
                content_id=UUID(result["content_id"]),
                captured_at=datetime.fromisoformat(result["captured_at"]),
                **values,
            )
        manifest = json.dumps(
            {
                "source_raw_id": result["raw_id"],
                "comment_ids": [
                    str(uuid5(UUID(result["raw_id"]), str(x["sample_position"])))
                    for x in result["comments"]
                ],
            },
            sort_keys=True,
        )
        import hashlib

        derived = insert(
            c,
            "raw_assets",
            task["org_id"],
            origin="processing",
            asset_kind="comment",
            processing_task_id=task["id"],
            parent_raw_asset_id=UUID(result["raw_id"]),
            external_content_id=UUID(result["content_id"]),
            body_text=manifest,
            sha256=hashlib.sha256(manifest.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"],
                task_id=task["id"],
                position=0,
                role="normalized_comments",
                raw_asset_id=derived,
            )
        )


def submit_normalization(c, p, raw_id, snapshot_id, handler):
    refresh(c, p)
    raw = Authorizer(c, p).read("raw_assets", raw_id)
    job = get(c, "collection_jobs", p.org_id, raw["collection_job_id"])
    from uuid import uuid4

    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "comments.normalize",
        "handler_version": "1",
        "source_id": job["source_id"],
        "raw_asset_id": raw_id,
        "business_code": job["business_code"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_external_calls": 0,
        "max_attempts": 1,
        "idempotency_key": str(raw_id),
    }
    existing = c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND kind='comments.normalize' AND idempotency_key=%s",
        (p.org_id, str(raw_id)),
    ).scalar_one_or_none()
    if existing:
        old = row(c, "tasks", p.org_id, existing)
        handler.freeze(c, old, Authorizer(c, p))
        return existing
    inputs = [
        {"role": "comments", "raw_asset_id": raw_id, "snapshot_id": None},
        {"role": "material", "snapshot_id": snapshot_id, "raw_asset_id": None},
    ]
    frozen = handler.freeze(c, values, Authorizer(c, p), inputs=inputs)
    values["input_sha256"] = input_digest(values, frozen)
    create_task(
        c,
        values,
        [
            {"role": "comments", "raw_asset_id": raw_id},
            {"role": "material", "snapshot_id": snapshot_id},
        ],
    )
    return tid
