"""No real databases or knowledge payloads in timer lifecycle tests."""

import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.knowledge import retention


def test_bounded_retention_maintenance_and_content_free_failure(caplog):
    engine = Mock()
    with patch.object(retention, "cleanup_expired", return_value=4) as sweep:
        assert retention.maintain(engine) == 4
        sweep.assert_called_once_with(engine, limit=50, scan_cursor={})
    with patch.object(retention, "cleanup_expired", side_effect=RuntimeError("secret body")):
        assert retention.maintain(engine) == 0
    assert "RuntimeError" in caplog.text and "secret body" not in caplog.text


@pytest.mark.parametrize("local,shared", [(True, False), (False, True)])
def test_workspace_startup_catches_up_and_shutdown_stops_maintenance(local, shared):
    seen = Event()
    engine = Mock()

    async def run():
        with (
            patch.object(retention, "settings", SimpleNamespace(local_single_user=local, passwordless_access=shared)),
            patch.object(retention, "application_engine", return_value=engine),
            patch.object(retention, "maintain", side_effect=lambda _: seen.set()) as sweep,
        ):
            async with retention.lifespan(None):
                assert await asyncio.to_thread(seen.wait, 2)
                assert sweep.call_count == 1
            engine.dispose.assert_called_once()

    asyncio.run(run())


def test_nonlocal_api_does_not_spawn_duplicate_local_maintenance():
    async def run():
        with (
            patch.object(retention, "settings", SimpleNamespace(local_single_user=False, passwordless_access=False)),
            patch.object(retention, "application_engine") as build,
        ):
            async with retention.lifespan(None):
                build.assert_not_called()

    asyncio.run(run())


def test_one_database_failure_does_not_block_later_items_and_cursor_advances(caplog):
    from contextlib import contextmanager
    from datetime import UTC, datetime
    from uuid import uuid4

    from sqlalchemy.exc import OperationalError

    from app.knowledge.purge import cleanup_expired

    rows = [
        {"org_id": uuid4(), "id": uuid4(), "lock_version": 1, "recycled_at": datetime.now(UTC)}
        for _ in range(2)
    ]
    query = Mock()
    query.exec_driver_sql.return_value.mappings.return_value.all.return_value = rows
    broken = Mock()
    broken.exec_driver_sql.side_effect = OperationalError(None, None, RuntimeError("private SQL"))
    healthy = Mock()
    healthy.exec_driver_sql.return_value.scalar_one.return_value = True

    @contextmanager
    def connection(c):
        yield c

    engine = Mock()
    engine.connect.side_effect = lambda: connection(query)
    engine.begin.side_effect = [connection(broken), connection(healthy)]
    cursor = {}
    assert cleanup_expired(engine, scan_cursor=cursor) == 1
    assert cursor["after"] == (rows[-1]["recycled_at"], rows[-1]["org_id"], rows[-1]["id"])
    assert "private SQL" not in caplog.text
