from fastapi.responses import JSONResponse

from app.contracts.api import OPERATIONS, add_operation
from app.contracts.models import Envelope
from app.intelligence.creators import save, view
from app.security.http import preflight
from app.security.sessions import authenticate


def dispatch(
    *, request, engine, session=None, body=None, filters=None, csrf_token=None, idempotency_key=None
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    with engine.begin() as c:
        p = authenticate(c, session)
        data = (
            save(c, p, body, str(idempotency_key), remove=spec.name == "removeCreatorLink")
            if body
            else view(c, p, filters.business_code)
        )
    envelope = Envelope[spec.response](request_id=request.state.request_id, data=data)
    return JSONResponse(
        envelope.model_dump(mode="json"),
        status_code=spec.status,
        headers={"Cache-Control": "no-store"},
    )


def mount(app):
    for spec in OPERATIONS:
        if spec.name in ("getCreatorLinks", "saveCreatorLinks", "removeCreatorLink"):
            add_operation(spec, app, dispatch, preflight)
