"""Runtime bindings for the shared S05.1 wire contract; no design handler is mounted."""

from functools import lru_cache
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.contracts.api import OPERATIONS, add_operation, error_response, invalid_request
from app.contracts.models import ERROR_STATUS
from app.core.config import settings
from app.core.database import application_engine
from app.security.errors import Denied
from app.security.primitives import check_origin
from app.security.sessions import authenticate, login, logout, session_view, valid_csrf


@lru_cache(maxsize=1)
def get_engine():
    try:
        return application_engine()
    except (RuntimeError, SQLAlchemyError) as exc:
        raise Denied("SERVICE_NOT_READY") from exc


def preflight(request: Request, engine: Annotated[Engine, Depends(get_engine)]):
    request.state.request_id = uuid4()
    if not settings.secure_cookies and request.url.hostname not in ("127.0.0.1", "localhost"):
        raise Denied("SERVICE_NOT_READY")
    if settings.secure_cookies and request.url.scheme != "https":
        raise Denied("SERVICE_NOT_READY")
    if settings.local_single_user:
        from app.security.local import check_local
        check_local(request)
        if request.url.path == "/api/v1/session":
            if request.method != "GET":
                raise Denied("ACCESS_DENIED")
            return engine
    is_login = request.method == "POST" and request.url.path == "/api/v1/session"
    if not is_login:
        with engine.begin() as c:
            raw = request.cookies.get("cip_session")
            authenticate(
                c,
                raw,
                allow_revoked=request.method == "DELETE" and request.url.path == "/api/v1/session",
            )
            if request.method != "GET" and not valid_csrf(
                raw, request.headers.get("X-CSRF-Token", "")
            ):
                raise Denied("CSRF_INVALID")
    if request.method == "POST" and not check_origin(
        request.headers.get("origin"), settings.allowed_origins
    ):
        raise Denied("CSRF_INVALID")
    return engine


def dispatch(*, request, engine, body=None, session=None, csrf_token=None):
    if settings.local_single_user:
        from app.security.local import enter
        with engine.begin() as c:
            raw, payload = enter(c, session)
        result = response(payload, request.state.request_id)
        result.set_cookie("cip_session", raw, httponly=True, secure=False,
                          samesite="strict", max_age=8*3600, path="/api/v1")
        return result
    if request.method == "POST":
        if not check_origin(request.headers.get("origin"), settings.allowed_origins):
            raise Denied("CSRF_INVALID")
        # HTTP development cookies are limited to explicit local hostnames. Proxy headers
        # are never used as authority for Origin, client identity, scheme or cookie policy.
        if not settings.secure_cookies and request.url.hostname not in ("127.0.0.1", "localhost"):
            raise Denied("SERVICE_NOT_READY")
        if settings.secure_cookies and request.url.scheme != "https":
            raise Denied("SERVICE_NOT_READY")
        raw, payload = login(
            engine,
            body.org_id,
            body.login_name,
            body.password,
            request.client.host if request.client else "unknown",
            request_id=request.state.request_id,
        )
        result = response(payload, request.state.request_id)
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
    with engine.begin() as c:
        if request.method == "GET":
            payload = session_view(c, authenticate(c, session), session)
        else:
            logout(c, session, csrf_token, request_id=request.state.request_id)
            payload = {"acknowledged": True}
    result = response(payload, request.state.request_id)
    if request.method == "DELETE":
        result.delete_cookie(
            "cip_session",
            path="/api/v1",
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
        )
    return result


def response(payload, request_id):
    # Use the same contract serializers as FastAPI (UUID and UTC datetime in particular).
    from app.contracts.models import Acknowledged, Envelope, Session

    model = Acknowledged if "acknowledged" in payload else Session
    envelope = Envelope[model](request_id=request_id, data=payload)
    return JSONResponse(
        envelope.model_dump(mode="json"),
        headers={"X-Request-ID": str(envelope.request_id), "Cache-Control": "no-store"},
    )


def mount(app):
    app.add_exception_handler(RequestValidationError, invalid_request)

    @app.exception_handler(Denied)
    async def denied(request, exc):
        rid = str(getattr(request.state, "request_id", uuid4()))
        return JSONResponse(
            status_code=ERROR_STATUS[exc.code],
            content={
                "request_id": rid,
                "error": {"code": exc.code, "message": "请求未获准", "field_paths": []},
            },
            headers={"X-Request-ID": rid, "Cache-Control": "no-store"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request, exc):
        # Do not expose SQL, parameters, constraint messages or connection credentials.
        return error_response(
            "SERVICE_NOT_READY", request_id=getattr(request.state, "request_id", None)
        )

    for operation in OPERATIONS:
        if operation.stage == "S05.2" and operation.implementation == "implemented":
            add_operation(operation, app, dispatch, preflight)
