"""Explicit refresh writes; reads and reloads never start paid/source requests."""

from threading import Thread
from uuid import UUID

from fastapi.responses import JSONResponse

from app.contracts.api import OPERATIONS, add_operation
from app.contracts.models import Envelope
from app.core.config import settings
from app.intelligence.refresh import latest, start
from app.intelligence.refresh_worker import runtime
from app.security.errors import Denied
from app.security.http import preflight
from app.security.sessions import authenticate


def dispatch(
    *, request, engine, session=None, body=None, filters=None, csrf_token=None, idempotency_key=None
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    if body and not (settings.local_single_user or settings.passwordless_access):
        raise Denied("SERVICE_NOT_READY")
    with engine.begin() as c:
        p = authenticate(c, session)
        business = body.business_code if body else filters.business_code
        data = start(c, p, business, str(idempotency_key)) if body else latest(c, p, business)
        org = p.org_id
    if data["task_id"] and data["state"] in ("queued", "running"):
        runner = runtime(engine)
        if body:
            enqueue(engine, org, UUID(data["task_id"]))
        else:
            # Recover an expired lease without retransmitting any external request.
            runner.recover(org, UUID(data["task_id"]))
            with engine.begin() as c:
                data = latest(c, authenticate(c, session), business)
    envelope = Envelope[spec.response](request_id=request.state.request_id, data=data)
    return JSONResponse(
        envelope.model_dump(mode="json"),
        status_code=spec.status,
        headers={"Cache-Control": "no-store", "X-Request-ID": str(envelope.request_id)},
    )


def enqueue(engine, org, task_id):
    # Deliberately outside the short-lived common Celery queue. No automatic retries.
    if not (settings.local_single_user or settings.passwordless_access):
        raise Denied("SERVICE_NOT_READY")
    Thread(target=runtime(engine).run, args=(org, task_id), daemon=True).start()


def mount(app):
    for spec in OPERATIONS:
        if spec.name in ("refreshIntelligence", "getIntelligenceRefresh"):
            add_operation(spec, app, dispatch, preflight)
