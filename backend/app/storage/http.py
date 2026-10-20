"""Binary routes share exact contract registration and S05.2 authentication."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.contracts.api import OPERATIONS, add_operation, error_response
from app.contracts.models import Envelope, FileInfo
from app.core.config import settings
from app.security.errors import Denied
from app.security.http import preflight
from app.storage.external import fetch
from app.storage.local import LocalStore
from app.storage.service import authorize, open_download, read_chunk, replay_external, save


@lru_cache(maxsize=1)
def get_store():
    root = settings.storage_root
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return LocalStore(root / "files", settings.max_file_bytes)


def context(engine=Depends(preflight), store=Depends(get_store)):  # noqa: B008
    return engine, store


async def dispatch(
    *,
    request,
    engine,
    filters=None,
    body=None,
    session=None,
    csrf_token=None,
    idempotency_key=None,
    file_id=None,
):
    engine, store = engine
    if request.method == "GET":
        parent = (filters.parent_kind, filters.parent_id) if filters.parent_kind else None
        file, row = await run_in_threadpool(open_download, engine, store, session, file_id, parent)

        async def chunks():
            try:
                while True:
                    chunk = await run_in_threadpool(
                        read_chunk, engine, session, file_id, parent, file
                    )
                    if not chunk:
                        break
                    yield chunk
            finally:
                file.close()

        return StreamingResponse(
            chunks(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename=download; filename*=UTF-8''"
                + quote(row["original_name"] or "download", safe=""),
                "Content-Length": str(row["byte_size"]),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "X-Request-ID": str(request.state.request_id),
            },
        )
    meta = body or filters

    def check():
        with engine.begin() as c:
            authorize(c, session, meta)

    await run_in_threadpool(check)
    if body:
        existing = await run_in_threadpool(replay_external, engine, session, idempotency_key, meta)
        if existing:
            payload = Envelope[FileInfo](request_id=request.state.request_id, data=existing)
            return JSONResponse(
                payload.model_dump(mode="json"),
                status_code=201,
                headers={"X-Request-ID": str(payload.request_id), "Cache-Control": "no-store"},
            )
    with store.stage() as staged:
        source = None
        if body:
            remote_type, source = await run_in_threadpool(
                fetch, body.url, settings.external_media_hosts, staged
            )
            if remote_type != body.media_type:
                raise Denied("INVALID_FILE")
        else:
            if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
                raise Denied("INVALID_FILE")
            length = request.headers.get("content-length")
            if length and (not length.isdecimal() or int(length) > store.maximum):
                raise Denied("FILE_TOO_LARGE")
            async for chunk in request.stream():
                await run_in_threadpool(staged.write, chunk)
        info = await run_in_threadpool(
            save,
            engine,
            store,
            session,
            idempotency_key,
            meta,
            staged,
            source_url=source,
            request_id=request.state.request_id,
        )
    payload = Envelope[FileInfo](request_id=request.state.request_id, data=info)
    return JSONResponse(
        payload.model_dump(mode="json"),
        status_code=201,
        headers={"X-Request-ID": str(payload.request_id), "Cache-Control": "no-store"},
    )


class JsonLimit:
    """Bound small external metadata before FastAPI's JSON parser; never buffer upload bytes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not (
                scope.get("path")
                in ("/api/v1/files/from-url", "/api/v1/collection-jobs", "/api/v1/sources")
                or scope.get("path", "").startswith(("/api/v1/sources/", "/api/v1/tasks/"))
            )
            or scope.get("method") not in ("POST", "PATCH")
        ):
            return await self.app(scope, receive, send)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 16384:
                rid = str(uuid4())
                response = JSONResponse(
                    {
                        "request_id": rid,
                        "error": {
                            "code": "FILE_TOO_LARGE",
                            "message": "请求体过大",
                            "field_paths": [],
                        },
                    },
                    status_code=413,
                    headers={"X-Request-ID": rid, "Cache-Control": "no-store"},
                )
                return await response(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            if chunks:
                return chunks.pop(0)
            return await receive()

        return await self.app(scope, replay, send)


def mount(app):
    @app.exception_handler(OSError)
    async def storage_unavailable(request, exc):
        return error_response(
            "SERVICE_NOT_READY", request_id=getattr(request.state, "request_id", None)
        )

    app.add_middleware(JsonLimit)
    for spec in OPERATIONS:
        if spec.stage == "S05.3" and spec.implementation == "implemented":
            add_operation(spec, app, dispatch, context)
