"""Bounded, content-free maintenance shared by local API and Celery Beat."""

import logging
from contextlib import asynccontextmanager
from threading import Event, Lock, Thread
from weakref import WeakKeyDictionary

from app.core.config import settings
from app.core.database import application_engine
from app.knowledge.purge import cleanup_expired

log = logging.getLogger(__name__)
INTERVAL_SECONDS = 60
_cursors = WeakKeyDictionary()
_cursor_lock = Lock()


def maintain(engine):
    try:
        with _cursor_lock:
            cursor = _cursors.setdefault(engine, {})
            return cleanup_expired(engine, limit=50, scan_cursor=cursor)
    except Exception as exc:  # noqa: BLE001 - next tick retries only policy-expired rows
        log.warning("knowledge retention deferred error_type=%s", type(exc).__name__)
        return 0


@asynccontextmanager
async def lifespan(app):
    stop = Event()
    engine = application_engine() if (
        settings.local_single_user or settings.passwordless_access
    ) else None

    def loop():
        # Catch up once at startup; expiry is always rechecked in the DB function.
        while not stop.is_set():
            maintain(engine)
            stop.wait(INTERVAL_SECONDS)

    thread = Thread(target=loop, daemon=True, name="knowledge-retention") if engine else None
    if thread:
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread:
            thread.join(timeout=6)
        if engine:
            engine.dispose()
