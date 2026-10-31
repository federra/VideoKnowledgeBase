"""One-call model generation with frozen sources; batch publication is atomic."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.ai.deepseek import ModelError
from app.ai.feedback_task import private_file
from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import create_task
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import MemberPrincipal
from app.security.storage import audit, lock_org, receipt
from app.tasks.service import TaskError, input_digest
from app.topics import service
from app.topics.contracts import GenerationResult
from app.topics.model import system_prompt, validate_generation

KIND = "topic.generate"
VERSION = "1"


def context(c, p, business, spark_ids):
    refs = {"sparks": [], "knowledge": [], "intelligence": []}
    for sid in spark_ids:
        sp = service.spark(c, p, sid)
        identity = service.row(c, p, "topic_sparks", sid)
        refs["sparks"].append(
            {
                "id": str(sid),
                "revision_id": str(identity["current_revision_id"]),
                "version": sp["version"],
                "title": sp["title"],
                "text": sp["text"],
            }
        )
    # Freeze exact authorized published knowledge, not candidate heads or demo templates.
    az = Authorizer(c, p)
    candidates = c.exec_driver_sql(
        "SELECT r.id FROM knowledge_items k JOIN knowledge_publications pub ON pub.org_id=k.org_id AND pub.id=k.published_publication_id JOIN knowledge_revisions r ON r.org_id=pub.org_id AND r.id=pub.revision_id WHERE k.org_id=%s AND k.recycled_at IS NULL AND EXISTS(SELECT 1 FROM knowledge_businesses b WHERE b.org_id=r.org_id AND b.revision_id=r.id AND b.business_code=%s) ORDER BY (r.browse_category='genre') DESC,k.created_at DESC LIMIT 8",
        (p.org_id, business),
    ).scalars()
    for rid in candidates:
        try:
            r = az.read("knowledge_revisions", rid)
        except Denied:
            continue
        refs["knowledge"].append(
            {
                "revision_id": str(rid),
                "title": r["title"],
                "text": r["body_text"][:1600],
                "limitations": r.get("limitations"),
            }
        )
    from app.intelligence.service import selected, shanghai_date

    pairs = selected(
        c,
        p,
        business,
        shanghai_date(),
        platforms=("douyin", "hongguo"),
        board_capabilities=("douyin.search.microfilm",) if business == "story_short" else None,
    )
    seen = set()
    for snap, entries in sorted(pairs, key=lambda x: x[0]["created_at"], reverse=True):
        for entry in entries:
            obs = entry["entry"]["observation"]
            if obs["kind"] != "content" or obs["id"] in seen:
                continue
            raw_id = service.row(c, p, "content_observations", UUID(str(obs["id"])))["raw_asset_id"]
            seen.add(obs["id"])
            refs["intelligence"].append(
                {
                    "snapshot_id": str(snap["id"]),
                    "entry_id": str(entry["entry"]["id"]),
                    "raw_asset_id": str(raw_id),
                    "title": obs.get("display_name") or obs.get("title"),
                    "description": (obs.get("description") or "")[:1600],
                }
            )
            if len(refs["intelligence"]) == 8:
                break
        if len(refs["intelligence"]) == 8:
            break
    return refs


class Generate:
    version = VERSION
    max_external_calls = 1
    action = "content.write"

    def __init__(self, model=None, store=None):
        self.model = model
        self.store = store

    def freeze(self, c, task, az):
        from app.model_config import resolve

        service.authorize(c, az.p, task["business_code"], "content.write")
        raw = az.read("raw_assets", task["raw_asset_id"])
        data = json.loads(raw["body_text"])
        if (
            task["kind"] != KIND
            or task["max_external_calls"] != 1
            or task["max_attempts"] != 1
            or raw["submitted_by"] != task["requested_by"]
            or hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]
        ):
            raise TaskError("INVALID_INPUT")
        if data["business_code"] != task["business_code"] or data["mode"] not in (
            "batch",
            "brainstorm",
        ):
            raise TaskError("INVALID_INPUT")
        cfg = resolve(c, az.p, data["business_code"], "topic")
        # Current allocation and source must still match, while each saved revision remains immutable.
        if digest(jsonable(cfg)) != digest(data["config"]):
            raise TaskError("MODEL_NOT_CONFIGURED")
        service.check_sources(c, az.p, data["source_refs"])
        return data

    def execute_ticket(self, runner, ticket, checkpoint):
        from app.model_config import ConfiguredModel
        from app.storage.http import get_store

        store = self.store or get_store()
        execution = None

        def reserve(manifest):
            nonlocal execution
            checkpoint()
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
                    config_revision_id=UUID(ticket.payload["config"]["revision_id"]),
                    invocation_no=1,
                    input_sha256=manifest["input_sha256"],
                    input_manifest_file_id=fid,
                )
            store.forget(fid)

        output_file = None
        try:
            reply = (self.model or ConfiguredModel()).complete(
                ticket.payload["config"],
                system_prompt(ticket.payload["business_code"], ticket.payload["mode"]),
                json.dumps(
                    {
                        "instructions": ticket.payload["instructions"],
                        "source_refs": ticket.payload["source_refs"],
                    },
                    ensure_ascii=False,
                ),
                GenerationResult.model_json_schema(),
                reserve=reserve,
            )
            output = validate_generation(reply.validated, ticket.payload["mode"])
        except (ModelError, ValueError) as exc:
            code = str(exc) if isinstance(exc, ModelError) else "INVALID_RESPONSE"
            if execution:
                failure_meta = exc if isinstance(exc, ModelError) else reply
                with runner.engine.begin() as c:
                    lock_org(c, ticket.org)
                    task = service.row(
                        c,
                        MemberPrincipal(ticket.org, self._member(c, ticket)),
                        "tasks",
                        ticket.task,
                    )
                    text = exc.raw_text if isinstance(exc, ModelError) else reply.raw_text
                    if text is not None:
                        output_file = private_file(c, store, task, text)
                    c.execute(
                        metadata.tables["ai_executions"]
                        .update()
                        .where(metadata.tables["ai_executions"].c.id == execution)
                        .values(
                            result_state="failed",
                            safe_error_code=code,
                            provider_request_id=failure_meta.provider_request_id,
                            input_tokens=failure_meta.input_tokens,
                            output_tokens=failure_meta.output_tokens,
                            finished_at=datetime.now(UTC),
                            output_file_id=output_file,
                        )
                    )
                if output_file:
                    store.forget(output_file)
            raise TaskError(code) from None
        with runner.engine.begin() as c:
            lock_org(c, ticket.org)
            task = service.row(
                c, MemberPrincipal(ticket.org, self._member(c, ticket)), "tasks", ticket.task
            )
            output_file = private_file(c, store, task, reply.raw_text)
            c.execute(
                metadata.tables["ai_executions"]
                .update()
                .where(metadata.tables["ai_executions"].c.id == execution)
                .values(
                    result_state="completed",
                    output_file_id=output_file,
                    provider_request_id=reply.provider_request_id,
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    finished_at=datetime.now(UTC),
                )
            )
        store.forget(output_file)
        checkpoint()
        return {"execution_id": str(execution), "output": output}

    @staticmethod
    def _member(c, ticket):
        return c.exec_driver_sql(
            "SELECT execution_authorized_by FROM tasks WHERE org_id=%s AND id=%s",
            (ticket.org, ticket.task),
        ).scalar_one()

    def publish(self, c, task, result):
        from app.storage.http import get_store

        p = MemberPrincipal(task["org_id"], task["execution_authorized_by"])
        data = self.freeze(c, task, Authorizer(c, p))
        execution = service.row(c, p, "ai_executions", UUID(result["execution_id"]))
        if execution["task_id"] != task["id"] or execution["result_state"] != "completed":
            raise TaskError("INVALID_INPUT")
        file = service.row(c, p, "file_objects", execution["output_file_id"])
        import hashlib

        with (self.store or get_store()).open(p.org_id, file["id"]) as stream:
            body = stream.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024 or hashlib.sha256(body).hexdigest() != file["sha256"]:
            raise TaskError("INVALID_RESPONSE")
        value = validate_generation(json.loads(body), data["mode"])
        if value != result["output"]:
            raise TaskError("INVALID_RESPONSE")
        from app.topics.quality import screen

        if any(
            screen(fields, data["source_refs"])["status"] == "risk" for fields in value["topics"]
        ):
            raise TaskError("ORIGINALITY_RISK")
        if data["mode"] == "batch":
            for fields in value["topics"]:
                service.add(
                    c,
                    p,
                    data["business_code"],
                    fields,
                    origin="batch",
                    source_refs=data["source_refs"],
                    generation_task_id=task["id"],
                )
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        raw = insert(
            c,
            "raw_assets",
            p.org_id,
            origin="processing",
            asset_kind="response",
            processing_task_id=task["id"],
            parent_raw_asset_id=task["raw_asset_id"],
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        for position, ref in enumerate(
            [{"raw_asset_id": raw}, {"ai_execution_id": execution["id"]}]
        ):
            c.execute(
                metadata.tables["task_outputs"]
                .insert()
                .values(
                    org_id=p.org_id,
                    task_id=task["id"],
                    position=position,
                    role="topic_generation",
                    **ref,
                )
            )


def jsonable(value):
    return json.loads(json.dumps(value, default=str))


def start(c, p, key, request, handler=None):
    from app.model_config import resolve

    service.authorize(c, p, request.business_code, "content.write")
    if handler is None:
        from app.topics.generation_v2 import GenerateV2

        handler = GenerateV2()

    def perform():
        cfg = jsonable(resolve(c, p, request.business_code, "topic"))
        active = c.exec_driver_sql(
            "SELECT 1 FROM tasks WHERE org_id=%s AND business_code=%s AND requested_by=%s AND kind=%s AND state IN('queued','running','cancel_requested')",
            (p.org_id, request.business_code, p.member_id, KIND),
        ).first()
        if active:
            raise Denied("VERSION_CONFLICT")
        refs = context(c, p, request.business_code, request.spark_ids)
        data = {
            "business_code": request.business_code,
            "mode": request.mode,
            "instructions": request.instructions,
            "source_refs": refs,
            "config": cfg,
        }
        text = json.dumps(data, sort_keys=True, ensure_ascii=False)
        rid = insert(
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
            "handler_version": handler.version,
            "business_code": request.business_code,
            "raw_asset_id": rid,
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": handler.max_external_calls,
            "idempotency_key": "topic/" + str(p.member_id) + "/" + key,
        }
        values["input_sha256"] = input_digest(values, handler.freeze(c, values, Authorizer(c, p)))
        create_task(
            c,
            values,
            [
                {"role": "topic_sources", "raw_asset_id": rid},
                {"role": "model", "ai_config_revision_id": UUID(cfg["revision_id"])},
            ],
        )
        audit(c, p.org_id, p.member_id, "topic.generation.requested", "task", tid)
        return {"id": str(tid)}

    saved = receipt(c, p, "generateTopics", key, request.model_dump(mode="json"), perform)
    return read(c, p, UUID(saved["id"]))


def read(c, p, ident):
    task = service.row(c, p, "tasks", ident)
    if task["kind"] != KIND or task["requested_by"] != p.member_id:
        raise Denied("NOT_FOUND")
    service.authorize(c, p, task["business_code"])
    az = Authorizer(c, p)
    raw = az.read("raw_assets", task["raw_asset_id"])
    data = json.loads(raw["body_text"])
    service.check_sources(c, p, data["source_refs"])
    output = None
    if task["state"] == "succeeded":
        rid = c.exec_driver_sql(
            "SELECT raw_asset_id FROM task_outputs WHERE org_id=%s AND task_id=%s AND role='topic_generation' AND raw_asset_id IS NOT NULL",
            (p.org_id, ident),
        ).scalar_one()
        out = az.read("raw_assets", rid)
        output = validate_generation(json.loads(out["body_text"]), data["mode"])
    saved = c.exec_driver_sql(
        "SELECT topic_id FROM topic_saved_generations WHERE org_id=%s AND task_id=%s",
        (p.org_id, ident),
    ).scalar_one_or_none()
    return {
        "id": ident,
        "task_id": ident,
        "state": task["state"],
        "safe_error_code": task["safe_error_code"],
        "business_code": task["business_code"],
        "mode": data["mode"],
        "saved_topic_id": saved,
        "result": output,
        "input": {
            "spark_ids": [x["id"] for x in data["source_refs"].get("sparks", [])],
            "instructions": data["instructions"],
        },
        "created_at": task["created_at"],
    }


def save(c, p, key, ident, request):
    value = read(c, p, ident)
    service.authorize(c, p, value["business_code"], "content.write")

    def perform():
        value = read(c, p, ident)
        if (
            value["state"] != "succeeded"
            or value["mode"] != "brainstorm"
            or value["saved_topic_id"]
        ):
            raise Denied("VERSION_CONFLICT")
        task = service.row(c, p, "tasks", ident)
        data = json.loads(service.row(c, p, "raw_assets", task["raw_asset_id"])["body_text"])
        from app.topics.quality import screen

        fields = request.fields.model_dump()
        if str(task["handler_version"]) == "2":
            from app.topics.generation_v2 import validate_saved_creation

            validate_saved_creation(c, p, task, data, fields)
        elif screen(fields, data["source_refs"])["status"] == "risk":
            raise TaskError("ORIGINALITY_RISK")
        tid = service.add(
            c,
            p,
            value["business_code"],
            request.fields.model_dump(),
            origin="brainstorm",
            source_refs=data["source_refs"],
            generation_task_id=ident,
        )
        insert(
            c,
            "topic_saved_generations",
            p.org_id,
            task_id=ident,
            topic_id=tid,
            created_by=p.member_id,
        )
        return {"id": str(tid)}

    saved = receipt(
        c,
        p,
        "saveGeneratedTopic",
        key,
        {"id": str(ident), **request.model_dump(mode="json")},
        perform,
    )
    return service.topic(c, p, UUID(saved["id"]))
