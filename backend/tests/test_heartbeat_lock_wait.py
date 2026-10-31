from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.tasks.service import Runner


class Locked(Exception):
    sqlstate = "55P03"


def test_lock_wait_is_neither_revocation_nor_success_and_next_probe_revalidates():
    worker = Runner(None, {})
    ticket = SimpleNamespace(task=uuid4())
    with patch.object(
        worker, "heartbeat", side_effect=[DBAPIError(None, None, Locked()), True, False]
    ) as check:
        assert worker.checked_heartbeat(ticket) is None
        assert worker.checked_heartbeat(ticket) is True
        assert worker.checked_heartbeat(ticket) is False
        assert check.call_count == 3


def test_other_database_failures_are_not_suppressed():
    worker = Runner(None, {})
    with patch.object(
        worker, "heartbeat", side_effect=DBAPIError(None, None, RuntimeError("offline"))
    ), pytest.raises(DBAPIError):
        worker.checked_heartbeat(SimpleNamespace(task=uuid4()))
