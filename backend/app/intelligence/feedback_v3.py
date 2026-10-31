"""Bounded multi-work feedback: one invocation and independent sealed work results."""

import hashlib
import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from app.ai.feedback_v3 import PROMPT, BatchOutput, inspect_batch
from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence import feedback_v2 as v2
from app.intelligence.service import row
from app.model_config import resolve
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.read_authorizer import ReadAuthorizer
from app.security.sessions import MemberPrincipal, refresh
from app.security.storage import receipt
from app.tasks.service import TaskError, input_digest
from app.topics.execution import execute_call, stored_output
from app.topics.generation import jsonable

KIND = "audience.feedback"
VERSION = "3"


def frozen(c, p, task, *, auth=None):
    auth = auth or ReadAuthorizer(c, p)
    raw = row(c, "raw_assets", p.org_id, task["raw_asset_id"], auth=auth)
    data = json.loads(raw["body_text"])
    members = data.get("members", [])
    if (
        data.get("schema_version") != 3
        or not 1 <= len(members) <= 3
        or raw["submitted_by"] != task["requested_by"]
        or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
    ):
        raise Denied("SOURCE_UNAVAILABLE")
    entries = set()
    snapshots = set()
    days = set()
    for member in members:
        sample = member["sample"]
        expected = v2.sample(
            c,
            p,
            UUID(sample["entry_id"]),
            sample["business_code"],
            date.fromisoformat(sample["business_date"]),
            auth=auth,
        )
        if (
            expected != sample
            or v2.sample_key(expected) != member["sample_key"]
            or sample["business_code"] != task["business_code"]
        ):
            raise Denied("VERSION_CONFLICT")
        entries.add(sample["entry_id"])
        snapshots.add(sample["snapshot_id"])
        days.add(sample["business_date"])
    if len(entries) != len(members) or len(snapshots) != 1 or len(days) != 1:
        raise Denied("VERSION_CONFLICT")
    return data


class FeedbackV3:
    action = "research.run"

    def __init__(self, model=None, store=None):
        self.model, self.store = model, store

    def freeze(self, c, task, az):
        auth = ReadAuthorizer(c, az.p)
        auth.read("raw_assets", task["raw_asset_id"])
        data = frozen(c, az.p, task, auth=auth)
        if task["max_attempts"] != 1 or task["max_external_calls"] != 1:
            raise TaskError("INVALID_INPUT")
        snap = row(
            c,
            "intelligence_snapshots",
            az.p.org_id,
            UUID(data["members"][0]["sample"]["snapshot_id"]),
            auth=auth,
        )
        az.require("sources", snap["source_id"], self.action)
        if jsonable(resolve(c, az.p, task["business_code"], "feedback")) != data["config"]:
            raise Denied("MODEL_NOT_CONFIGURED")
        return data

    def execute_ticket(self, runner, ticket, checkpoint):
        data = ticket.payload
        samples = [x["sample"] for x in data["members"]]
        items = [
            {
                **{k: v for k, v in s.items() if k not in ("comments", "raw_ids")},
                "comments": [
                    {k: x[k] for k in ("id", "body_text", "like_count")} for x in s["comments"]
                ],
            }
            for s in samples
        ]
        return execute_call(
            runner,
            ticket,
            checkpoint,
            data["config"],
            PROMPT,
            json.dumps({"items": items}, ensure_ascii=False),
            BatchOutput.model_json_schema(),
            invocation_no=1,
            prompt_version="audience.feedback/v3",
            validator=lambda v: inspect_batch(samples, v),
            model=self.model,
            store=self.store,
        )

    def publish(self, c, task, result):
        p = MemberPrincipal(task["org_id"], task["execution_authorized_by"])
        data = self.freeze(c, task, Authorizer(c, p))
        samples = [x["sample"] for x in data["members"]]
        checked = stored_output(
            c,
            p,
            task["id"],
            UUID(result["execution_id"]),
            lambda v: inspect_batch(samples, v),
            store=self.store,
        )
        if checked != result["output"]:
            raise TaskError("INVALID_RESPONSE")
        for pos, (sample, item) in enumerate(zip(samples, checked["items"], strict=True)):
            v2.persist_result(
                c,
                p,
                task,
                sample,
                item["checked"],
                UUID(result["execution_id"]),
                entry_id=UUID(sample["entry_id"]),
                position=pos,
                include_execution=False,
            )
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=p.org_id,
                task_id=task["id"],
                position=len(samples),
                role="audience_feedback",
                ai_execution_id=UUID(result["execution_id"]),
            )
        )


def start_batch(c, p, members, business, day, *, key):
    """members: [{entry_id, sample_key, retry_of?}]; all inputs or no task."""
    refresh(c, p)
    if not 1 <= len(members) <= 3:
        raise Denied("VALIDATION_FAILED")
    normalized = [
        {
            "entry_id": str(x["entry_id"]),
            "sample_key": x["sample_key"],
            "retry_of": str(x["retry_of"]) if x.get("retry_of") else None,
        }
        for x in members
    ]
    normalized.sort(key=lambda x: x["entry_id"])
    if len({x["entry_id"] for x in normalized}) != len(normalized):
        raise Denied("VALIDATION_FAILED")
    auth = ReadAuthorizer(c, p)
    frozen_members = []
    for member in normalized:
        sample = v2.sample(c, p, UUID(member["entry_id"]), business, day, auth=auth)
        if v2.sample_key(sample) != member["sample_key"]:
            raise Denied("VERSION_CONFLICT")
        frozen_members.append({**member, "sample": sample})
    if len({x["sample"]["snapshot_id"] for x in frozen_members}) != 1:
        raise Denied("VERSION_CONFLICT")
    cfg = jsonable(resolve(c, p, business, "feedback"))
    snap = row(
        c,
        "intelligence_snapshots",
        p.org_id,
        UUID(frozen_members[0]["sample"]["snapshot_id"]),
        auth=auth,
    )
    Authorizer(c, p).require("sources", snap["source_id"], "research.run")

    def perform():
        latest = []
        for member in frozen_members:
            matches = v2.candidates(c, p, member["sample_key"])
            task = matches[0] if matches else None
            latest.append(task)
            if task and task["state"] in ("queued", "running", "succeeded"):
                continue
            if task:
                if member["retry_of"] != str(task["id"]) or task["state"] not in (
                    "failed",
                    "cancelled",
                    "expired",
                ):
                    raise Denied("VERSION_CONFLICT")
            elif member["retry_of"]:
                raise Denied("VERSION_CONFLICT")
        active = [x for x in latest if x and x["state"] in ("queued", "running", "succeeded")]
        if active:
            if (
                len(active) != len(latest)
                or len({x["id"] for x in active}) != 1
                or any(x["retry_of"] for x in frozen_members)
            ):
                raise Denied("VERSION_CONFLICT")
            task = active[0]
            return {
                "id": str(task["id"]),
                "analyses": [
                    v2.view(c, p, task, auth=auth, entry_id=UUID(x["entry_id"]))
                    for x in frozen_members
                ],
            }
        data = {
            "schema_version": 3,
            "members": frozen_members,
            "config": cfg,
            "match_key": v2.digest({"members": normalized, "config": cfg}),
        }
        text = json.dumps(data, ensure_ascii=False, sort_keys=True)
        raw = insert(
            c,
            "raw_assets",
            p.org_id,
            origin="manual",
            asset_kind="response",
            submitted_by=p.member_id,
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        tid = uuid4()
        values = {
            "id": tid,
            "org_id": p.org_id,
            "kind": KIND,
            "handler_version": VERSION,
            "business_code": business,
            "source_id": snap["source_id"],
            "raw_asset_id": raw,
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": 1,
            "idempotency_key": "feedback-v3/" + str(key),
        }
        values["input_sha256"] = input_digest(
            values, FeedbackV3().freeze(c, values, Authorizer(c, p))
        )
        raws = sorted({r for x in frozen_members for r in x["sample"]["raw_ids"]})
        create_task(
            c,
            values,
            [
                {"role": "freeze", "raw_asset_id": raw},
                {"role": "snapshot", "snapshot_id": snap["id"]},
                {"role": "config", "ai_config_revision_id": UUID(cfg["revision_id"])},
                *[{"role": "comments", "raw_asset_id": UUID(r)} for r in raws],
            ],
        )
        task = row(c, "tasks", p.org_id, tid)
        return {
            "id": str(tid),
            "analyses": [
                v2.view(c, p, task, data, entry_id=UUID(x["entry_id"])) for x in frozen_members
            ],
        }

    return receipt(
        c,
        p,
        "analyzeFeedbackBatch",
        key,
        {"members": normalized, "business": business, "day": str(day), "config": cfg},
        perform,
    )
