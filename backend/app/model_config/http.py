from fastapi.responses import JSONResponse

from app.contracts.api import Operation, add_operation
from app.contracts.models import Envelope
from app.model_config.contracts import (
    BindingsWrite,
    ConfigQuery,
    ConfigView,
    SourceView,
    SourceWrite,
)
from app.model_config.service import save_bindings, save_source, view
from app.security.http import preflight
from app.security.sessions import authenticate

OPERATIONS = [
    Operation(
        "GET",
        "/model-config",
        "getModelConfig",
        ConfigView,
        ("model.configure",),
        "S08",
        query=ConfigQuery,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/model-config/sources",
        "saveModelSource",
        SourceView,
        ("model.configure",),
        "S08",
        request=SourceWrite,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/model-config/bindings",
        "saveModelBindings",
        ConfigView,
        ("model.configure",),
        "S08",
        request=BindingsWrite,
        implementation="implemented",
    ),
]


def dispatch(
    *, request, engine, session=None, body=None, filters=None, csrf_token=None, idempotency_key=None
):
    spec = next(x for x in OPERATIONS if x.name == request.scope["route"].operation_id)
    with engine.begin() as c:
        p = authenticate(c, session)
        if spec.name == "getModelConfig":
            data = view(c, p, filters.business_code)
        else:
            data = (save_source if spec.name == "saveModelSource" else save_bindings)(
                c, p, body, str(idempotency_key)
            )
    return JSONResponse(
        Envelope[spec.response](request_id=request.state.request_id, data=data).model_dump(
            mode="json"
        ),
        headers={"Cache-Control": "no-store"},
    )


def mount(app):
    for spec in OPERATIONS:
        add_operation(spec, app, dispatch, preflight)
