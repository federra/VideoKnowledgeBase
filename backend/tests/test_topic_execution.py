import hashlib
import io
from uuid import uuid4

import pytest


def test_saved_response_requires_exact_task_hash_and_completed_execution(monkeypatch):
    from app.tasks.service import TaskError
    from app.topics import execution

    tid, eid, fid, org = uuid4(), uuid4(), uuid4(), uuid4()
    body = b'{"value":7}'
    rows = {
        ("ai_executions", eid): {
            "task_id": tid,
            "result_state": "completed",
            "output_file_id": fid,
        },
        ("file_objects", fid): {"id": fid, "sha256": hashlib.sha256(body).hexdigest()},
    }
    monkeypatch.setattr(execution.service, "row", lambda c, p, t, i: rows[(t, i)])

    class Store:
        def open(self, *_):
            return io.BytesIO(body)

    class Principal:
        org_id = org

    validator = lambda d: {"value": d["value"]}
    assert execution.stored_output(None, Principal(), tid, str(eid), validator, store=Store()) == {
        "value": 7
    }
    rows[("file_objects", fid)]["sha256"] = "0" * 64
    with pytest.raises(TaskError, match="INVALID_RESPONSE"):
        execution.stored_output(None, Principal(), tid, str(eid), validator, store=Store())
    rows[("ai_executions", eid)]["task_id"] = uuid4()
    with pytest.raises(TaskError, match="INVALID_INPUT"):
        execution.stored_output(None, Principal(), tid, str(eid), validator, store=Store())


def test_worker_limits_cover_all_console_timeouts():
    from app.topics.score_worker import execute as score
    from app.topics.worker import execute as generate
    assert score.soft_time_limit >= 630 and score.time_limit > score.soft_time_limit
    assert generate.soft_time_limit >= 1230 and generate.time_limit > generate.soft_time_limit
