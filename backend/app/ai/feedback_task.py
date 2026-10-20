"""Budgeted one-call feedback task: private execution files, sealed cited result."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select

from app.ai.deepseek import MODEL, PROMPT_VERSION, SYSTEM, DeepSeek, ModelError
from app.ai.feedback import FeedbackInput, FeedbackOutput, inspect_output
from app.collection.service import get, insert
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import authorized, row
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import MemberPrincipal, refresh
from app.security.storage import audit, lock_org
from app.tasks.service import TaskError, input_digest

PARAMETERS = {
    "prompt_version": PROMPT_VERSION,
    "system_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
    "max_output_tokens": 2048,
}


def sample(c, p, raw_id, snapshot_id):
    raw = Authorizer(c, p).read("raw_assets", raw_id)
    snap = row(c, "intelligence_snapshots", p.org_id, snapshot_id)
    authorized(c, p, snap)
    job = get(c, "collection_jobs", p.org_id, raw["collection_job_id"])
    source = get(c, "sources", p.org_id, job["source_id"])
    if (
        job["business_date"] != snap["business_date"]
        or job["business_code"] != snap["business_code"]
        or job["capability_code"] != "douyin.comments.capture"
    ):
        raise TaskError("INVALID_INPUT")
    entries = (
        c.exec_driver_sql(
            "SELECT e.id FROM snapshot_entries e JOIN content_observations o ON o.id=e.content_observation_id AND o.org_id=e.org_id WHERE e.org_id=%s AND e.snapshot_id=%s AND o.content_id=%s",
            (p.org_id, snapshot_id, source["content_id"]),
        )
        .scalars()
        .all()
    )
    if len(entries) != 1:
        raise TaskError("INVALID_INPUT")
    t = metadata.tables["comment_evidence"]
    comments = list(
        c.execute(
            select(t)
            .where(
                t.c.org_id == p.org_id,
                t.c.raw_asset_id == raw_id,
                t.c.content_id == source["content_id"],
            )
            .order_by(t.c.sample_position)
        ).mappings()
    )
    body = {
        "business_code": snap["business_code"],
        "business_date": snap["business_date"],
        "snapshot_id": snapshot_id,
        "snapshot_version": snap["version_no"],
        "entry_id": entries[0],
        "platform_code": "douyin",
        "sampling_description": "TikHub首屏20条上限；接口默认排序，不代表全体观众，未采回复或后续页",
        "comments": [
            {
                k: x[k]
                for k in (
                    "id",
                    "platform_comment_id",
                    "body_text",
                    "like_count",
                    "captured_at",
                    "posted_at_raw",
                )
            }
            for x in comments
        ],
    }
    return FeedbackInput.model_validate(body)


def private_file(c, store, task, body):
    data = body.encode()
    fid = uuid4()
    with store.stage() as staged:
        staged.write(data)
        store.journal(staged, task["org_id"], fid)
        store.publish(staged, task["org_id"], fid)
        insert(
            c,
            "file_objects",
            task["org_id"],
            id=fid,
            storage_backend="local",
            storage_key=f"{task['org_id']}/{fid}",
            original_name=None,
            media_type="application/json",
            byte_size=staged.size,
            sha256=staged.sha256,
            validation_state="accepted",
            uploaded_by=task["execution_authorized_by"],
        )
    return fid


class FeedbackTask:
    action = "collection.run"

    def __init__(self, model=None, store=None):
        self.model = model or DeepSeek()
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
        targets = {
            key: [x.get(key) for x in inputs if x.get(key)]
            for key in ("snapshot_id", "raw_asset_id", "ai_config_revision_id")
        }
        if (
            len(inputs) != 3
            or any(len(v) != 1 for v in targets.values())
            or task["max_external_calls"] != 1
            or task["max_attempts"] != 1
        ):
            raise TaskError("INVALID_INPUT")
        config = get(c, "ai_config_revisions", task["org_id"], targets["ai_config_revision_id"][0])
        conn = get(c, "provider_connections", task["org_id"], config["provider_connection_id"])
        source = az.require("sources", task["source_id"], self.action)
        if (
            not conn["enabled"]
            or conn["provider_code"] != "deepseek"
            or conn["secret_ref"] != "DEEPSEEK_KEY"
            or config["task_kind"] != "audience.feedback"
            or config["model_identifier"] != MODEL
            or config["parameters"] != PARAMETERS
            or config["output_schema"] != FeedbackOutput.model_json_schema()
        ):
            raise TaskError("INVALID_INPUT")
        data = sample(c, az.p, targets["raw_asset_id"][0], targets["snapshot_id"][0])
        raw = get(c, "raw_assets", task["org_id"], targets["raw_asset_id"][0])
        job = get(c, "collection_jobs", task["org_id"], raw["collection_job_id"])
        if source["id"] != job["source_id"] or task["business_code"] != data.business_code:
            raise TaskError("INVALID_INPUT")
        return {
            "sample": data.model_dump(mode="json"),
            "config_id": str(config["id"]),
            "config_sha256": config["content_sha256"],
            "connection_version": conn["lock_version"],
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        from app.storage.http import get_store

        store = self.store or get_store()
        sample_input = FeedbackInput.model_validate(ticket.payload["sample"])
        execution = None

        def reserve(manifest):
            nonlocal execution
            with runner.engine.begin() as c:
                task = runner.live(c, ticket)
                if not task:
                    raise TaskError("ACCESS_REVOKED")
                runner.validate(c, task)
                fid = private_file(
                    c, store, task, json.dumps(manifest, ensure_ascii=False, sort_keys=True)
                )
                execution = insert(
                    c,
                    "ai_executions",
                    ticket.org,
                    task_id=ticket.task,
                    attempt_id=ticket.attempt,
                    config_revision_id=UUID(ticket.payload["config_id"]),
                    invocation_no=1,
                    input_sha256=manifest["input_sha256"],
                    input_manifest_file_id=fid,
                )
            store.forget(fid)

        try:
            reply = self.model.feedback(sample_input, reserve=reserve)
        except ModelError as exc:
            if execution:
                with runner.engine.begin() as c:
                    lock_org(c, ticket.org)
                    task = row(c, "tasks", ticket.org, ticket.task)
                    output = (
                        private_file(c, store, task, exc.raw_text)
                        if exc.raw_text is not None
                        else None
                    )
                    c.execute(
                        metadata.tables["ai_executions"]
                        .update()
                        .where(metadata.tables["ai_executions"].c.id == execution)
                        .values(
                            result_state="failed",
                            safe_error_code=str(exc),
                            finished_at=datetime.now(UTC),
                            output_file_id=output,
                            provider_request_id=exc.provider_request_id,
                            input_tokens=exc.input_tokens,
                            output_tokens=exc.output_tokens,
                        )
                    )
                if output:
                    store.forget(output)
            raise TaskError(str(exc)) from None
        with runner.engine.begin() as c:
            lock_org(c, ticket.org)
            task = row(c, "tasks", ticket.org, ticket.task)
            output = private_file(c, store, task, reply.raw_text)
            c.execute(
                metadata.tables["ai_executions"]
                .update()
                .where(metadata.tables["ai_executions"].c.id == execution)
                .values(
                    result_state=reply.validated["output"]["result_state"],
                    provider_request_id=reply.provider_request_id,
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    output_file_id=output,
                    finished_at=datetime.now(UTC),
                )
            )
        store.forget(output)
        checkpoint()
        return {"execution_id": str(execution), "validated": reply.validated}

    def publish(self, c, task, result):
        payload = self.freeze(
            c, task, Authorizer(c, MemberPrincipal(task["org_id"], task["execution_authorized_by"]))
        )
        checked = inspect_output(
            FeedbackInput.model_validate(payload["sample"]), result["validated"]["output"]
        )
        execution = get(c, "ai_executions", task["org_id"], UUID(result["execution_id"]))
        if (
            execution["task_id"] != task["id"]
            or execution["result_state"] != checked["output"]["result_state"]
        ):
            raise TaskError("INVALID_INPUT")
        from app.storage.http import get_store

        store = self.store or get_store()
        saved = row(c, "file_objects", task["org_id"], execution["output_file_id"])
        with store.open(task["org_id"], execution["output_file_id"]) as stream:
            body = stream.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024 or hashlib.sha256(body).hexdigest() != saved["sha256"]:
            raise TaskError("INVALID_INPUT")
        persisted = inspect_output(
            FeedbackInput.model_validate(payload["sample"]), json.loads(body)
        )
        if persisted != checked:
            raise TaskError("INVALID_INPUT")
        if execution["result_state"] != "completed":
            raise TaskError("INSUFFICIENT_MATERIAL")
        snapshot = UUID(payload["sample"]["snapshot_id"])
        version = c.exec_driver_sql(
            "SELECT coalesce(max(version_no),0)+1 FROM feedback_snapshots WHERE org_id=%s AND snapshot_id=%s",
            (task["org_id"], snapshot),
        ).scalar_one()
        fid = insert(
            c,
            "feedback_snapshots",
            task["org_id"],
            id=uuid5(task["id"], "feedback"),
            snapshot_id=snapshot,
            version_no=version,
            task_id=task["id"],
            ai_execution_id=execution["id"],
            sampling_description=payload["sample"]["sampling_description"],
            sample_count=checked["sample_count"],
            classified_count=checked["classified_count"],
            coverage_note="仅一条关键词作品的首屏小样本；结论及建议待验证，不代表市场整体",
            summary=checked["output"]["summary"],
        )
        for position, comment in enumerate(payload["sample"]["comments"]):
            c.execute(
                metadata.tables["feedback_comments"]
                .insert()
                .values(
                    org_id=task["org_id"],
                    feedback_id=fid,
                    comment_id=UUID(comment["id"]),
                    position=position,
                )
            )
        for claim in checked["output"]["claims"]:
            cid = insert(
                c,
                "feedback_claims",
                task["org_id"],
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
                    .values(
                        org_id=task["org_id"], feedback_id=fid, claim_id=cid, comment_id=UUID(ident)
                    )
                )
        c.exec_driver_sql("SELECT cip_seal('feedback_snapshots',%s,%s)", (task["org_id"], fid))
        for position, target in enumerate(
            [{"feedback_id": fid}, {"ai_execution_id": execution["id"]}]
        ):
            c.execute(
                metadata.tables["task_outputs"]
                .insert()
                .values(
                    org_id=task["org_id"],
                    task_id=task["id"],
                    position=position,
                    role="audience_feedback",
                    **target,
                )
            )


def submit_feedback(c, p, raw_id, snapshot_id, handler):
    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    data = sample(c, p, raw_id, snapshot_id)
    raw = get(c, "raw_assets", p.org_id, raw_id)
    job = get(c, "collection_jobs", p.org_id, raw["collection_job_id"])
    az.require("sources", job["source_id"], handler.action)
    existing = c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND kind='audience.feedback' AND idempotency_key=%s",
        (p.org_id, str(raw_id)),
    ).scalar_one_or_none()
    if existing:
        handler.freeze(c, row(c, "tasks", p.org_id, existing), az)
        return existing
    if not az.allowed("model.configure", {("org", str(p.org_id))}):
        raise Denied("ACCESS_DENIED")
    config = c.exec_driver_sql(
        "SELECT id FROM ai_config_revisions WHERE org_id=%s AND config_key='audience.feedback.v1' ORDER BY version_no DESC LIMIT 1",
        (p.org_id,),
    ).scalar_one_or_none()
    if not config:
        conn = insert(
            c,
            "provider_connections",
            p.org_id,
            name="DeepSeek Flash 观众反馈",
            provider_code="deepseek",
            secret_ref="DEEPSEEK_KEY",
            enabled=True,
        )
        definition = {
            "parameters": PARAMETERS,
            "model": MODEL,
            "schema": FeedbackOutput.model_json_schema(),
        }
        config = insert(
            c,
            "ai_config_revisions",
            p.org_id,
            config_key="audience.feedback.v1",
            version_no=1,
            task_kind="audience.feedback",
            provider_connection_id=conn,
            model_identifier=MODEL,
            parameters=PARAMETERS,
            output_schema=FeedbackOutput.model_json_schema(),
            content_sha256=digest(definition),
            created_by=p.member_id,
        )
    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "audience.feedback",
        "handler_version": "1",
        "source_id": job["source_id"],
        "business_code": data.business_code,
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_external_calls": 1,
        "max_attempts": 1,
        "idempotency_key": str(raw_id),
    }
    inputs = [
        {"role": "material", "snapshot_id": snapshot_id},
        {"role": "comments", "raw_asset_id": raw_id},
        {"role": "config", "ai_config_revision_id": config},
    ]
    values["input_sha256"] = input_digest(values, handler.freeze(c, values, az, inputs=inputs))
    create_task(c, values, inputs)
    audit(c, p.org_id, p.member_id, "feedback.submitted", "task", tid)
    return tid
