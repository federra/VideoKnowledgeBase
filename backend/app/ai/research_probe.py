"""S07.1 one-call definition validation; never creates production research objects."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.ai.deepseek import MODEL, DeepSeek, ModelError
from app.ai.feedback_task import private_file
from app.ai.research import DEFINITIONS, ResearchInput, freeze_input, inspect_output, system_prompt
from app.collection.service import get, insert
from app.connectors.tikhub_series import CAPABILITY
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import authorized, row
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import MemberPrincipal, refresh
from app.security.storage import audit, lock_org
from app.tasks.service import TaskError, input_digest

KIND = "research.definition-probe"
CONFIG = "research.decompose.v1"
PARAMETERS = {
    "definition_version": CONFIG,
    "system_sha256": hashlib.sha256(system_prompt("decompose").encode()).hexdigest(),
    "max_output_tokens": 2048,
}


def sample(c, p, snapshot_id, entry_id):
    snap = row(c, "intelligence_snapshots", p.org_id, snapshot_id)
    authorized(c, p, snap)
    entry = row(c, "snapshot_entries", p.org_id, entry_id)
    if entry["snapshot_id"] != snapshot_id or not entry["content_observation_id"]:
        raise TaskError("INVALID_INPUT")
    obs = row(c, "content_observations", p.org_id, entry["content_observation_id"])
    raw = Authorizer(c, p).read("raw_assets", obs["raw_asset_id"])
    job = get(c, "collection_jobs", p.org_id, raw["collection_job_id"])
    if (
        not snap["sealed_at"]
        or job["capability_code"] != CAPABILITY
        or job["id"] != snap["job_id"]
        or not obs["description"]
        or snap["business_code"] != "motion_comic"
    ):
        raise TaskError("INSUFFICIENT_MATERIAL")
    value = ResearchInput.model_validate(
        {
            "business_code": snap["business_code"],
            "scope": "synopsis",
            "outcome_exposure": "observed",
            "segments": [
                {
                    "id": "p1",
                    "source_kind": "content_observation",
                    "source_id": str(obs["id"]),
                    "source_version": 1,
                    "text": obs["description"],
                }
            ],
            "missing_inputs": [
                "完整剧本及实际集数覆盖",
                "音视频及时间点",
                "评论原文",
                "批准的评级边界",
                "事前发布条件与独立校准样本",
            ],
        }
    )
    return value, snap, raw


class Probe:
    action = "research.run"

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
        if len(inputs) != 2 or task["max_attempts"] != 1 or task["max_external_calls"] != 1:
            raise TaskError("INVALID_INPUT")
        target = next((x for x in inputs if x.get("snapshot_id")), None)
        cfg = next((x for x in inputs if x.get("ai_config_revision_id")), None)
        if not target or not cfg or not target["role"].startswith("entry:"):
            raise TaskError("INVALID_INPUT")
        value, snap, raw = sample(c, az.p, target["snapshot_id"], UUID(target["role"][6:]))
        source = az.require("sources", task["source_id"], self.action)
        az.require("sources", task["source_id"], "research.submit")
        config = get(c, "ai_config_revisions", task["org_id"], cfg["ai_config_revision_id"])
        conn = get(c, "provider_connections", task["org_id"], config["provider_connection_id"])
        definition = {
            "parameters": PARAMETERS,
            "model": MODEL,
            "schema": DEFINITIONS["decompose"].model_json_schema(),
        }
        if (
            source["id"] != snap["source_id"]
            or task["business_code"] != value.business_code
            or not conn["enabled"]
            or conn["provider_code"] != "deepseek"
            or conn["secret_ref"] != "DEEPSEEK_KEY"
            or config["config_key"] != CONFIG
            or config["task_kind"] != KIND
            or config["model_identifier"] != MODEL
            or config["parameters"] != PARAMETERS
            or config["output_schema"] != definition["schema"]
            or config["content_sha256"] != digest(definition)
        ):
            raise TaskError("INVALID_INPUT")
        return {
            "sample": value.model_dump(mode="json"),
            "sample_sha256": freeze_input("decompose", value)["sha256"],
            "snapshot_id": str(snap["id"]),
            "snapshot_version": snap["version_no"],
            "raw_id": str(raw["id"]),
            "raw_sha256": raw["sha256"],
            "config_id": str(config["id"]),
            "config_sha256": config["content_sha256"],
            "connection_version": conn["lock_version"],
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        from app.storage.http import get_store

        store = self.store or get_store()
        sample_input = ResearchInput.model_validate(ticket.payload["sample"])
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
            reply = self.model.research("decompose", sample_input, reserve=reserve)
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
        execution = get(c, "ai_executions", task["org_id"], UUID(result["execution_id"]))
        if execution["task_id"] != task["id"] or execution["config_revision_id"] != UUID(
            payload["config_id"]
        ):
            raise TaskError("INVALID_INPUT")
        from app.storage.http import get_store

        store = self.store or get_store()
        saved = row(c, "file_objects", task["org_id"], execution["output_file_id"])
        with store.open(task["org_id"], execution["output_file_id"]) as stream:
            body = stream.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024 or hashlib.sha256(body).hexdigest() != saved["sha256"]:
            raise TaskError("INVALID_INPUT")
        checked = inspect_output(
            "decompose", ResearchInput.model_validate(payload["sample"]), json.loads(body)
        )
        if (
            checked != result["validated"]
            or execution["result_state"] != checked["output"]["result_state"]
        ):
            raise TaskError("INVALID_INPUT")
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(
                org_id=task["org_id"],
                task_id=task["id"],
                position=0,
                role="definition_validation_only",
                ai_execution_id=execution["id"],
            )
        )
        audit(
            c,
            task["org_id"],
            task["execution_authorized_by"],
            "research.definition_validated",
            "task",
            task["id"],
        )


def submit_probe(c, p, snapshot_id, entry_id, handler):
    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    value, snap, _ = sample(c, p, snapshot_id, entry_id)
    az.require("sources", snap["source_id"], "research.submit")
    az.require("sources", snap["source_id"], handler.action)
    key = CONFIG + ":" + str(entry_id)
    existing = c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND kind=%s AND idempotency_key=%s",
        (p.org_id, KIND, key),
    ).scalar_one_or_none()
    if existing:
        handler.freeze(c, row(c, "tasks", p.org_id, existing), az)
        return existing
    if not az.allowed("model.configure", {("org", str(p.org_id))}):
        raise Denied("ACCESS_DENIED")
    config = c.exec_driver_sql(
        "SELECT id FROM ai_config_revisions WHERE org_id=%s AND config_key=%s ORDER BY version_no DESC LIMIT 1",
        (p.org_id, CONFIG),
    ).scalar_one_or_none()
    if not config:
        conn = c.exec_driver_sql(
            "SELECT id FROM provider_connections WHERE org_id=%s AND provider_code='deepseek' AND secret_ref='DEEPSEEK_KEY' AND enabled ORDER BY created_at,id LIMIT 1",
            (p.org_id,),
        ).scalar_one_or_none()
        if not conn:
            conn = insert(
                c,
                "provider_connections",
                p.org_id,
                name="DeepSeek S07任务验证",
                provider_code="deepseek",
                secret_ref="DEEPSEEK_KEY",
                enabled=True,
            )
        definition = {
            "parameters": PARAMETERS,
            "model": MODEL,
            "schema": DEFINITIONS["decompose"].model_json_schema(),
        }
        config = insert(
            c,
            "ai_config_revisions",
            p.org_id,
            config_key=CONFIG,
            version_no=1,
            task_kind=KIND,
            provider_connection_id=conn,
            model_identifier=MODEL,
            parameters=PARAMETERS,
            output_schema=definition["schema"],
            content_sha256=digest(definition),
            created_by=p.member_id,
        )
    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": KIND,
        "handler_version": "1",
        "source_id": snap["source_id"],
        "business_code": value.business_code,
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_external_calls": 1,
        "max_attempts": 1,
        "idempotency_key": key,
    }
    inputs = [
        {"role": "entry:" + str(entry_id), "snapshot_id": snapshot_id},
        {"role": "config", "ai_config_revision_id": config},
    ]
    values["input_sha256"] = input_digest(values, handler.freeze(c, values, az, inputs=inputs))
    create_task(c, values, inputs)
    audit(c, p.org_id, p.member_id, "research.definition_submitted", "task", tid)
    return tid
