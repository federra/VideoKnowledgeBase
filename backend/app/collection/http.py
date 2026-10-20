"""Console and collection routes use the same session/CSRF/idempotency boundary."""

from uuid import uuid4

from fastapi.responses import JSONResponse

from app.collection.console import (
    control_task,
    create_source,
    list_sources,
    list_tasks,
    patch_source,
    task_view,
)
from app.collection.paging import page
from app.collection.service import submit
from app.connectors.redfox import VERSION
from app.contracts.api import OPERATIONS, add_operation
from app.contracts.models import Envelope
from app.security.http import preflight
from app.security.sessions import authenticate
from app.tasks.handlers import registry
from app.tasks.service import Runner

NAMES = {
    "listSources",
    "createSource",
    "updateSource",
    "startCollection",
    "listTasks",
    "getTask",
    "cancelTask",
    "retryTask",
}


def dispatch(
    *,
    request,
    engine,
    body=None,
    session=None,
    csrf_token=None,
    idempotency_key=None,
    filters=None,
    source_id=None,
    task_id=None,
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    with engine.begin() as c:
        p = authenticate(c, session)
        key = str(idempotency_key or uuid4())
        match spec.name:
            case "listSources":
                data = page(
                    c,
                    p,
                    list_sources(c, p, filters.business_code),
                    kind="sources",
                    business=filters.business_code,
                    limit=filters.limit,
                    cursor=filters.cursor,
                    q=filters.q,
                )
            case "createSource":
                data = create_source(c, p, body, key)
            case "updateSource":
                data = patch_source(c, p, source_id, body, key)
            case "startCollection":
                data = submit(c, p, body, key, registry()[("collect.redfox", VERSION)])
            case "listTasks":
                data = page(
                    c,
                    p,
                    list_tasks(c, p, filters.business_code),
                    kind="tasks",
                    business=filters.business_code,
                    limit=filters.limit,
                    cursor=filters.cursor,
                    q=filters.q,
                )
            case "getTask":
                data = task_view(c, p, task_id)
            case _:
                data = control_task(
                    c,
                    p,
                    task_id,
                    body,
                    Runner(engine, registry()),
                    "retry" if spec.name == "retryTask" else "cancel",
                    key,
                )
    envelope = Envelope[spec.response](request_id=request.state.request_id, data=data)
    return JSONResponse(
        envelope.model_dump(mode="json"),
        status_code=spec.status,
        headers={"X-Request-ID": str(envelope.request_id), "Cache-Control": "no-store"},
    )


def mount(app):
    for spec in OPERATIONS:
        if spec.name in NAMES:
            add_operation(spec, app, dispatch, preflight)
