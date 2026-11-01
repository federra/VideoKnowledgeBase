from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from app.accounts import contracts as t
from app.accounts import service
from app.contracts.api import Operation, add_operation
from app.contracts.models import Envelope, Session
from app.core.config import settings
from app.security.errors import Denied
from app.security.http import get_engine, preflight
from app.security.local import check_local
from app.security.primitives import check_origin
from app.security.sessions import authenticate, limit_login

OPERATIONS = [
    Operation(
        "POST",
        "/access/register",
        "registerAccess",
        Session,
        (),
        "S08.6",
        request=t.RegisterRequest,
        public=True,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/access",
        "getAccess",
        t.AccessView,
        (),
        "S08.6",
        public=True,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/access/setup",
        "setupAccess",
        Session,
        (),
        "S08.6",
        request=t.SetupRequest,
        public=True,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/users",
        "listUsers",
        t.UserList,
        ("member.manage",),
        "S08.6",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/users",
        "createUser",
        t.UserView,
        ("member.manage",),
        "S08.6",
        request=t.UserCreate,
        implementation="implemented",
    ),
    Operation(
        "PATCH",
        "/users/{member_id}",
        "updateUser",
        t.UserView,
        ("member.manage",),
        "S08.6",
        request=t.UserUpdate,
        implementation="implemented",
    ),
]


def public_preflight(request: Request, engine: Annotated[Engine, Depends(get_engine)]):
    request.state.request_id = uuid4()
    if request.method == "POST":
        if request.url.path.endswith("/setup"):
            check_local(request)
        elif (
            not settings.secure_cookies and request.url.hostname not in ("localhost", "127.0.0.1")
        ) or (settings.secure_cookies and request.url.scheme != "https"):
            raise Denied("ACCESS_DENIED")
        if not check_origin(request.headers.get("origin"), settings.allowed_origins):
            raise Denied("CSRF_INVALID")
    return engine


def dispatch(
    *,
    request,
    engine,
    body=None,
    session=None,
    csrf_token=None,
    idempotency_key=None,
    member_id=None,
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    raw = None
    if spec.name == "registerAccess":
        if not settings.user_accounts_enabled:
            raise Denied("ACCESS_DENIED")
        with engine.begin() as c:
            binding = service.require_installation(c)
        limit_login(
            engine,
            binding["org_id"],
            "register:" + body.email,
            request.client.host if request.client else "unknown",
        )
    with engine.begin() as c:
        if spec.name == "getAccess":
            data = service.access(c)
        elif spec.name == "setupAccess":
            raw, data = service.setup(c, body)
        elif spec.name == "registerAccess":
            raw, data = service.register(c, body)
        else:
            if not settings.user_accounts_enabled:
                raise Denied("ACCESS_DENIED")
            p = authenticate(c, session)
            service.require_installation(c, p.org_id)
            if spec.name == "listUsers":
                data = service.list_users(c, p)
            elif spec.name == "createUser":
                data = service.create(c, p, idempotency_key, body)
            else:
                data = service.update(c, p, idempotency_key, member_id, body)
    result = JSONResponse(
        Envelope[spec.response](request_id=request.state.request_id, data=data).model_dump(
            mode="json"
        ),
        headers={"Cache-Control": "no-store", "X-Request-ID": str(request.state.request_id)},
    )
    if raw:
        result.set_cookie(
            "cip_session",
            raw,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            max_age=8 * 3600,
            path="/api/v1",
        )
    return result


def mount(app):
    for spec in OPERATIONS:
        add_operation(spec, app, dispatch, public_preflight if spec.public else preflight)
