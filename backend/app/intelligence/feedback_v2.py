"""Exact-entry, exact-sample audience analysis with persistent one-call tasks."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from app.ai.feedback_v2 import PROMPT, Output, inspect_output
from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import row
from app.model_config import resolve
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import MemberPrincipal, refresh
from app.security.storage import receipt
from app.tasks.service import TaskError, input_digest
from app.topics.execution import execute_call, stored_output
from app.topics.generation import jsonable

KIND = "audience.feedback"
VERSION = "2"


def sample(c, p, entry_id, business, day, *, auth=None, base=None):
    if auth is not None:
        return auth.memo(
            ("feedback.sample", entry_id, business, day),
            lambda: _sample(c, p, entry_id, business, day, base=base, auth_proxy=auth),
        )
    return _sample(c, p, entry_id, business, day, base=base)


def _sample(c, p, entry_id, business, day, *, base=None, auth_proxy=None):
    from app.intelligence.feedback import entry_feedback

    value = (
        base
        if base is not None
        else entry_feedback(c, p, entry_id, business, day, _analysis=False, auth=auth_proxy)
    )
    if not value["comments"]:
        raise Denied("INSUFFICIENT_MATERIAL")
    value = {
        k: value[k]
        for k in (
            "entry_id",
            "snapshot_id",
            "snapshot_version",
            "business_code",
            "business_date",
            "platform_code",
            "sampling_description",
            "coverage_note",
            "comments",
        )
    }
    value["comments"] = value["comments"][:20]
    ids = [x["id"] for x in value["comments"]]
    raws = (
        c.exec_driver_sql(
            "SELECT DISTINCT raw_asset_id FROM comment_evidence WHERE org_id=%s AND id=ANY(%s)",
            (p.org_id, ids),
        )
        .scalars()
        .all()
    )
    az = auth_proxy or Authorizer(c, p)
    for rid in raws:
        az.read("raw_assets", rid)
    value["raw_ids"] = sorted(map(str, raws))
    return jsonable(value)


def sample_key(value):
    return digest(value)


def model_ready(c, p, business):
    try:
        resolve(c, p, business, "feedback")
        return True
    except (Denied, TaskError):
        return False


def members(data):
    return (
        data["members"]
        if data.get("schema_version") == 3
        else [{"sample": data["sample"], "sample_key": data["sample_key"]}]
    )


def candidates(c, p, key):
    rows = c.exec_driver_sql(
        "SELECT t.*,r.body_text FROM tasks t JOIN raw_assets r ON r.org_id=t.org_id AND r.id=t.raw_asset_id WHERE t.org_id=%s AND t.kind='audience.feedback' AND t.handler_version IN ('2','3') ORDER BY t.created_at DESC,t.id DESC",
        (p.org_id,),
    ).mappings()
    return [
        r for r in rows if any(x["sample_key"] == key for x in members(json.loads(r["body_text"])))
    ]


def frozen(c, p, task, *, auth=None):
    if task["handler_version"] == "3":
        from app.intelligence.feedback_v3 import frozen as batch_frozen

        return batch_frozen(c, p, task, auth=auth)
    raw = row(c, "raw_assets", p.org_id, task["raw_asset_id"], auth=auth)
    if hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]:
        raise Denied("SOURCE_UNAVAILABLE")
    data = json.loads(raw["body_text"])
    if data.get("schema_version") != 2 or raw["submitted_by"] != task["requested_by"]:
        raise Denied("SOURCE_UNAVAILABLE")
    from datetime import date

    expected = sample(
        c,
        p,
        UUID(data["sample"]["entry_id"]),
        data["sample"]["business_code"],
        date.fromisoformat(data["sample"]["business_date"]),
        auth=auth,
    )
    if data["sample"] != expected or data["sample_key"] != sample_key(expected):
        raise Denied("VERSION_CONFLICT")
    return data


def view(c, p, task, data=None, *, auth=None, entry_id=None):
    data = data or frozen(c, p, task, auth=auth)
    targets = members(data)
    chosen = (
        next((x for x in targets if str(x["sample"]["entry_id"]) == str(entry_id)), None)
        if entry_id
        else (targets[0] if len(targets) == 1 else None)
    )
    if chosen is None:
        raise Denied("VALIDATION_FAILED")
    sample = chosen["sample"]
    result = (
        c.exec_driver_sql(
            "SELECT f.id,f.classified_count,e.result_state FROM feedback_snapshots f JOIN ai_executions e ON e.org_id=f.org_id AND e.id=f.ai_execution_id WHERE f.org_id=%s AND f.task_id=%s AND (f.entry_id IS NULL OR f.entry_id=%s) AND f.sealed_at IS NOT NULL",
            (p.org_id, task["id"], UUID(sample["entry_id"])),
        )
        .mappings()
        .one_or_none()
    )
    state = (
        ("completed" if result["classified_count"] else "insufficient_evidence") if result else None
    )
    s = sample
    return {
        "id": str(task["id"]),
        "entry_id": s["entry_id"],
        "snapshot_id": s["snapshot_id"],
        "business_code": s["business_code"],
        "business_date": s["business_date"],
        "sample_key": chosen["sample_key"],
        "state": task["state"],
        "result_state": state,
        "safe_error_code": task.get("safe_error_code"),
        "feedback_id": str(result["id"]) if result else None,
    }


def analysis(c, p, ident, entry_id=None):
    from app.security.read_authorizer import ReadAuthorizer

    auth = ReadAuthorizer(c, p)
    task = row(c, "tasks", p.org_id, ident)
    if task["kind"] != KIND or task["handler_version"] not in ("2", "3"):
        raise Denied("NOT_FOUND")
    return view(c, p, task, auth=auth, entry_id=entry_id)


def decorate(c, p, value, *, auth=None):
    value.update(
        sample_key=None,
        analysis_model_ready=model_ready(c, p, value["business_code"]),
        analysis=None,
        summary=None,
    )
    if not value["comments"]:
        return value
    current = sample(
        c,
        p,
        value["entry_id"],
        value["business_code"],
        value["business_date"],
        auth=auth,
        base=value,
    )
    key = sample_key(current)
    value["sample_key"] = key
    tasks = candidates(c, p, key)
    if tasks:
        task = tasks[0]
        data = frozen(c, p, task, auth=auth)
        value["analysis"] = view(c, p, task, data, auth=auth, entry_id=value["entry_id"])
        if task["state"] == "succeeded" and value["analysis"]["feedback_id"]:
            from app.intelligence.feedback import read_feedback

            full = read_feedback(c, p, value["analysis"]["feedback_id"], auth=auth)
            value.update(
                {
                    k: full[k]
                    for k in (
                        "comments",
                        "claims",
                        "sample_count",
                        "classified_count",
                        "sampling_description",
                        "coverage_note",
                        "summary",
                    )
                }
            )
            value.update(
                status="ready", feedback_id=full["id"], feedback_version=full["version_no"]
            )
    return value


class FeedbackV2:
    action = "research.run"

    def __init__(self, model=None, store=None):
        self.model, self.store = model, store

    def freeze(self, c, task, az):
        az.read("raw_assets", task["raw_asset_id"])
        data = frozen(c, az.p, task)
        if (
            task["max_attempts"] != 1
            or task["max_external_calls"] != 1
            or task["business_code"] != data["sample"]["business_code"]
        ):
            raise TaskError("INVALID_INPUT")
        snap = row(c, "intelligence_snapshots", az.p.org_id, UUID(data["sample"]["snapshot_id"]))
        az.require("sources", snap["source_id"], self.action)
        if jsonable(resolve(c, az.p, task["business_code"], "feedback")) != data["config"]:
            raise Denied("MODEL_NOT_CONFIGURED")
        return data

    def execute_ticket(self, runner, ticket, checkpoint):
        data = ticket.payload
        return execute_call(
            runner,
            ticket,
            checkpoint,
            data["config"],
            PROMPT,
            json.dumps(
                {
                    **{k: v for k, v in data["sample"].items() if k not in ("comments", "raw_ids")},
                    "comments": [
                        {k: x[k] for k in ("id", "body_text", "like_count")}
                        for x in data["sample"]["comments"]
                    ],
                },
                ensure_ascii=False,
            ),
            Output.model_json_schema(),
            invocation_no=1,
            prompt_version="audience.feedback/v2",
            validator=lambda v: inspect_output(data["sample"], v),
            model=self.model,
            store=self.store,
        )

    def publish(self, c, task, result):
        p = MemberPrincipal(task["org_id"], task["execution_authorized_by"])
        data = self.freeze(c, task, Authorizer(c, p))
        checked = stored_output(
            c,
            p,
            task["id"],
            UUID(result["execution_id"]),
            lambda v: inspect_output(data["sample"], v),
            store=self.store,
        )
        if checked != result["output"]:
            raise TaskError("INVALID_RESPONSE")
        persist_result(c, p, task, data["sample"], checked, UUID(result["execution_id"]))


def persist_result(
    c, p, task, sample, checked, execution_id, *, entry_id=None, position=0, include_execution=True
):
    snapshot = UUID(sample["snapshot_id"])
    version = c.exec_driver_sql(
        "SELECT coalesce(max(version_no),0)+1 FROM feedback_snapshots WHERE org_id=%s AND snapshot_id=%s",
        (p.org_id, snapshot),
    ).scalar_one()
    fid = insert(
        c,
        "feedback_snapshots",
        p.org_id,
        id=uuid5(task["id"], "feedback" if entry_id is None else "feedback/" + str(entry_id)),
        entry_id=entry_id,
        snapshot_id=snapshot,
        version_no=version,
        task_id=task["id"],
        ai_execution_id=execution_id,
        sampling_description=sample["sampling_description"],
        sample_count=checked["sample_count"],
        classified_count=checked["classified_count"],
        coverage_note=sample["coverage_note"]
        .replace("未执行AI分析，", "")
        .replace("未执行AI分析；", "")
        .replace("未执行AI分析、", ""),
        summary=checked["output"]["summary"],
    )
    for pos, comment in enumerate(sample["comments"]):
        c.execute(
            metadata.tables["feedback_comments"]
            .insert()
            .values(org_id=p.org_id, feedback_id=fid, comment_id=UUID(comment["id"]), position=pos)
        )
    for claim in checked["output"]["claims"]:
        cid = insert(
            c,
            "feedback_claims",
            p.org_id,
            feedback_id=fid,
            kind=claim["kind"],
            claim_key=claim["claim_key"],
            text=claim["text"],
            details={
                k: v
                for k, v in claim.items()
                if k not in ("kind", "claim_key", "text", "comment_ids")
            },
            support_count=checked["support_counts"][claim["claim_key"]],
        )
        for ident in claim["comment_ids"]:
            c.execute(
                metadata.tables["feedback_claim_evidence"]
                .insert()
                .values(org_id=p.org_id, feedback_id=fid, claim_id=cid, comment_id=UUID(ident))
            )
    c.exec_driver_sql("SELECT cip_seal('feedback_snapshots',%s,%s)", (p.org_id, fid))
    targets = [{"feedback_id": fid}]
    if include_execution:
        targets.append({"ai_execution_id": execution_id})
    for pos, target in enumerate(targets, start=position):
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=p.org_id,
                task_id=task["id"],
                position=pos,
                role="audience_feedback",
                **target,
            )
        )
    return fid


def start(c, p, entry_id, business, day, expected_sample_key, *, key, retry_of=None):
    refresh(c, p)
    data_sample = sample(c, p, entry_id, business, day)
    sk = sample_key(data_sample)
    if sk != expected_sample_key:
        raise Denied("VERSION_CONFLICT")
    cfg = jsonable(resolve(c, p, business, "feedback"))
    snap = row(c, "intelligence_snapshots", p.org_id, UUID(data_sample["snapshot_id"]))
    Authorizer(c, p).require("sources", snap["source_id"], "research.run")
    match = digest({"sample_key": sk, "config": cfg})

    def perform():
        matches = candidates(c, p, sk)
        latest = matches[0] if matches else None
        if latest and latest["state"] in ("queued", "running", "succeeded"):
            if retry_of:
                raise Denied("VERSION_CONFLICT")
            return view(c, p, latest, entry_id=entry_id)
        if latest:
            if retry_of != latest["id"] or latest["state"] not in (
                "failed",
                "cancelled",
                "expired",
            ):
                raise Denied("VERSION_CONFLICT")
        elif retry_of:
            raise Denied("VERSION_CONFLICT")
        data = {
            "schema_version": 2,
            "sample": data_sample,
            "sample_key": sk,
            "config": cfg,
            "match_key": match,
            "retry_of": str(retry_of) if retry_of else None,
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
        task = {
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
            "idempotency_key": "feedback-v2/" + str(key),
        }
        task["input_sha256"] = input_digest(task, FeedbackV2().freeze(c, task, Authorizer(c, p)))
        create_task(
            c,
            task,
            [
                {"role": "freeze", "raw_asset_id": raw},
                {"role": "snapshot", "snapshot_id": UUID(data_sample["snapshot_id"])},
                {"role": "config", "ai_config_revision_id": UUID(cfg["revision_id"])},
                *[{"role": "comments", "raw_asset_id": UUID(x)} for x in data_sample["raw_ids"]],
            ],
        )
        return view(c, p, row(c, "tasks", p.org_id, tid), data)

    return receipt(
        c,
        p,
        "analyzeEntryFeedback",
        key,
        {
            "entry_id": str(entry_id),
            "business": business,
            "day": str(day),
            "sample_key": sk,
            "config": cfg,
            "retry_of": str(retry_of) if retry_of else None,
        },
        perform,
    )
