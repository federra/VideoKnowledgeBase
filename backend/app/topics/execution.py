"""Bounded model invocation with immutable private evidence and exact response replay."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from app.ai.deepseek import ModelError
from app.ai.feedback_task import private_file
from app.collection.service import insert
from app.core.models import metadata
from app.security.sessions import MemberPrincipal
from app.security.storage import lock_org
from app.tasks.service import TaskError, external_calls
from app.topics import service


def stored_output(c, p, task_id, execution_id, validator, *, store=None):
    from app.storage.http import get_store

    e = service.row(c, p, "ai_executions", UUID(str(execution_id)))
    if e["task_id"] != task_id or e["result_state"] != "completed" or not e["output_file_id"]:
        raise TaskError("INVALID_INPUT")
    f = service.row(c, p, "file_objects", e["output_file_id"])
    with (store or get_store()).open(p.org_id, f["id"]) as stream:
        body = stream.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024 or hashlib.sha256(body).hexdigest() != f["sha256"]:
        raise TaskError("INVALID_RESPONSE")
    try:
        return validator(json.loads(body))
    except (ValueError, TypeError, KeyError) as exc:
        raise TaskError("INVALID_RESPONSE") from exc


def execute_call(
    runner,
    ticket,
    checkpoint,
    config,
    system,
    user,
    schema,
    *,
    invocation_no,
    prompt_version,
    validator,
    model=None,
    store=None,
):
    from app.model_config import ConfiguredModel
    from app.storage.http import get_store

    store = store or get_store()
    execution_id = None
    reply = None

    def reserve(manifest):
        nonlocal execution_id
        checkpoint()
        if execution_id is not None:
            raise TaskError("BUDGET_EXHAUSTED")
        # The manifest covers the exact provider payload, never credentials.
        manifest = {**manifest, "prompt_version": prompt_version}
        with runner.engine.begin() as c:
            lock_org(c, ticket.org)
            task = runner.live(c, ticket)
            if not task:
                raise TaskError("ACCESS_REVOKED")
            runner.validate(c, task)
            if (
                not 1 <= invocation_no <= task["max_external_calls"]
                or external_calls(c, ticket.task) >= task["max_external_calls"]
            ):
                raise TaskError("BUDGET_EXHAUSTED")
            fid = private_file(
                c, store, task, json.dumps(manifest, ensure_ascii=False, sort_keys=True)
            )
            execution_id = insert(
                c,
                "ai_executions",
                ticket.org,
                task_id=ticket.task,
                attempt_id=ticket.attempt,
                config_revision_id=UUID(str(config["revision_id"])),
                invocation_no=invocation_no,
                input_sha256=manifest["input_sha256"],
                input_manifest_file_id=fid,
            )
        store.forget(fid)

    def finish(state, code=None, error=None):
        if execution_id is None:
            return
        meta = error if isinstance(error, ModelError) else reply
        text = (
            error.raw_text if isinstance(error, ModelError) else (reply.raw_text if reply else None)
        )
        output_id = None
        with runner.engine.begin() as c:
            lock_org(c, ticket.org)
            actor = c.exec_driver_sql(
                "SELECT execution_authorized_by FROM tasks WHERE org_id=%s AND id=%s",
                (ticket.org, ticket.task),
            ).scalar_one()
            task = service.row(c, MemberPrincipal(ticket.org, actor), "tasks", ticket.task)
            if text is not None:
                output_id = private_file(c, store, task, text)
            c.execute(
                metadata.tables["ai_executions"]
                .update()
                .where(
                    metadata.tables["ai_executions"].c.org_id == ticket.org,
                    metadata.tables["ai_executions"].c.id == execution_id,
                )
                .values(
                    result_state=state,
                    safe_error_code=code,
                    finished_at=datetime.now(UTC),
                    output_file_id=output_id,
                    provider_request_id=meta.provider_request_id if meta else None,
                    input_tokens=meta.input_tokens if meta else None,
                    output_tokens=meta.output_tokens if meta else None,
                )
            )
        if output_id:
            store.forget(output_id)

    try:
        reply = (model or ConfiguredModel()).complete(config, system, user, schema, reserve=reserve)
        if execution_id is None:
            raise TaskError("INVALID_INPUT")
        output = validator(reply.validated)
    except (ModelError, ValueError, TaskError) as exc:
        code = (
            exc.code
            if isinstance(exc, TaskError)
            else str(exc)
            if isinstance(exc, ModelError)
            else "INVALID_RESPONSE"
        )
        finish("failed", code, exc)
        raise TaskError(code) from None
    finish("completed")
    checkpoint()
    return {"execution_id": str(execution_id), "output": output}
