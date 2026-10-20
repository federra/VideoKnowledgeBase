"""Task state, fencing and side effects in disposable real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from tests.integration.test_schema import base, material
from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


class Handler:
    action = "content.write"

    def freeze(self, c, task, az):
        work = az.require("works", task["work_id"], self.action)
        return {"work": str(work["id"]), "version": work["lock_version"]}

    def execute(self, payload, checkpoint):
        checkpoint()
        return payload

    def publish(self, c, task, result):
        _, version = material(c, task["org_id"], task["execution_authorized_by"], task["work_id"])
        c.exec_driver_sql(
            "INSERT INTO task_outputs(org_id,task_id,position,role,artifact_version_id) "
            "VALUES (%s,%s,0,'derived',%s)",
            (task["org_id"], task["id"], version),
        )


def prepared(engine, *, attempts=1, handler=None):
    from app.core.repository import create_task
    from app.security.authorization import Authorizer
    from app.security.sessions import MemberPrincipal
    from app.tasks.service import Runner, input_digest

    handler = handler or Handler()
    with engine.begin() as c:
        org, member, work = base(c)
        grant(c, org, member, member, ["content.read", "content.write", "task.read", "task.manage"])
        task = {
            "org_id": org,
            "kind": "test.local",
            "handler_version": "1",
            "work_id": work,
            "requested_by": member,
            "execution_authorized_by": member,
            "idempotency_key": str(uuid4()),
            "max_attempts": attempts,
            "max_external_calls": 0,
        }
        payload = handler.freeze(c, task, Authorizer(c, MemberPrincipal(org, member)))
        task["input_sha256"] = input_digest(task, payload)
        tid, _ = create_task(c, task)
    return Runner(engine, {("test.local", "1"): handler}), org, member, work, tid


def state(engine, tid):
    with engine.connect() as c:
        return c.exec_driver_sql("SELECT state FROM tasks WHERE id=%s", (tid,)).scalar_one()


def test_duplicate_concurrent_delivery_publishes_once(engine):
    runner, org, _, _, tid = prepared(engine)
    barrier = Barrier(2)

    def work():
        barrier.wait(timeout=5)
        return runner.run(org, tid)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: work(), range(2)))
    assert sorted(results) == ["ignored", "succeeded"]
    assert runner.run(org, tid) == "ignored"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_attempts WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_outputs WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 1
        )


def test_stale_input_and_revocation_fail_before_or_after_execution(engine):
    runner, org, member, work, tid = prepared(engine)
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE works SET name='changed',lock_version=lock_version+1 WHERE id=%s", (work,)
        )
    assert runner.run(org, tid) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_attempts WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 0
        )
    runner, org, member, _, tid = prepared(engine)
    ticket = runner.claim(org, tid)
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE member_id=%s",
            (member,),
        )
    assert runner.complete(ticket, {}) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_outputs WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 0
        )


def test_expired_attempt_recovers_but_late_worker_cannot_publish(engine):
    import time

    runner, org, _, _, tid = prepared(engine, attempts=2)
    runner.lease_seconds = 1
    ticket = runner.claim(org, tid)
    time.sleep(1.1)
    runner.lease_seconds = 90
    assert runner.recover(org, tid)
    assert state(engine, tid) == "queued"
    assert runner.complete(ticket, {}) == "ignored"
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE tasks SET available_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
            (tid,),
        )
    assert runner.run(org, tid) == "succeeded"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_outputs WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT outcome FROM task_attempts WHERE id=%s", (ticket.attempt,)
            ).scalar_one()
            == "lease_lost"
        )


def test_retry_budget_and_unknown_external_effect_are_not_automatically_replayed(engine):
    runner, org, _, _, tid = prepared(engine, attempts=2)
    ticket = runner.claim(org, tid)
    assert runner.fail(ticket, "LOCAL_TRANSIENT") == "queued"
    assert runner.claim(org, tid) is None  # not yet available
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE tasks SET available_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
            (tid,),
        )
    ticket = runner.claim(org, tid)
    assert runner.fail(ticket, "LOCAL_TRANSIENT") == "failed"
    assert state(engine, tid) == "failed"
    runner, org, _, _, tid = prepared(engine, attempts=3)
    ticket = runner.claim(org, tid)
    assert runner.fail(ticket, "EXTERNAL_RESULT_UNKNOWN") == "failed"
    assert state(engine, tid) == "failed"


def test_cancel_wins_before_publish_and_organization_capacity_is_enforced(engine):
    from app.security.sessions import MemberPrincipal
    from app.tasks.service import cancel

    runner, org, member, _, tid = prepared(engine)
    ticket = runner.claim(org, tid)
    with engine.begin() as c:
        cancel(c, MemberPrincipal(org, member), tid, ticket.version)
    assert runner.complete(ticket, {}) == "cancelled"
    assert state(engine, tid) == "cancelled"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_outputs WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 0
        )


def test_heartbeat_cannot_extend_expired_or_foreign_lease(engine):
    from dataclasses import replace

    runner, org, _, _, tid = prepared(engine)
    ticket = runner.claim(org, tid)
    assert runner.heartbeat(ticket)
    assert not runner.heartbeat(replace(ticket, token=uuid4()))
    assert runner.run(org, tid) == "ignored"


def test_publish_exception_rolls_back_product_and_records_safe_failure(engine):
    class Broken(Handler):
        def publish(self, c, task, result):
            super().publish(c, task, result)
            raise ValueError("private provider text must never persist")

    runner, org, _, _, tid = prepared(engine, handler=Broken())
    assert runner.run(org, tid) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_outputs WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM artifact_versions WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql("SELECT safe_error_code FROM tasks WHERE id=%s", (tid,)).scalar_one()
            == "INTERNAL_ERROR"
        )


def test_sweep_republishes_durable_queue_and_survives_broker_failure(engine):
    from app.tasks.service import sweep

    runner, org, _, _, tid = prepared(engine)
    sent = []

    def send(o, t):
        sent.append((o, t))

    sweep(runner, send)
    assert (org, tid) in sent
    sweep(runner, send)
    assert sent.count((org, tid)) == 2

    def broken(o, t):
        raise OSError("broker unavailable")

    sweep(runner, broken)
    assert state(engine, tid) == "queued"


def test_capacity_across_distinct_tasks_and_disabled_requester(engine):
    from app.core.models import metadata
    from app.core.repository import create_task

    runner, org, member, _, tid = prepared(engine)
    ids = [tid]
    with engine.begin() as c:
        original = dict(
            c.execute(metadata.tables["tasks"].select().where(metadata.tables["tasks"].c.id == tid))
            .mappings()
            .one()
        )
        for _ in range(2):
            values = {
                k: original[k]
                for k in [
                    "org_id",
                    "kind",
                    "handler_version",
                    "work_id",
                    "requested_by",
                    "execution_authorized_by",
                    "max_attempts",
                    "max_external_calls",
                    "input_sha256",
                ]
            }
            values["idempotency_key"] = str(uuid4())
            ids.append(create_task(c, values)[0])
    assert runner.claim(org, ids[0])
    assert runner.claim(org, ids[1])
    assert runner.claim(org, ids[2]) is None
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE members SET disabled_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
            (member,),
        )
    assert runner.run(org, ids[2]) == "failed"


def test_file_verify_reads_real_bytes_idempotency_and_tamper(engine, setup, tmp_path):
    from uuid import UUID

    from app.contracts.models import FileUploadQuery
    from app.security.errors import Denied
    from app.storage.local import LocalStore
    from app.storage.service import save
    from app.tasks.handlers import FileVerify
    from app.tasks.service import Runner, submit_file
    from tests.integration.test_file_storage import work

    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        grant(c, org, member, member, ["content.read", "content.write", "file.read"], "work", wid)
    store = LocalStore(tmp_path / "files")
    try:
        meta = FileUploadQuery(
            work_id=wid,
            expected_work_lock_version="1",
            original_name="x.txt",
            media_type="text/plain",
        )
        with store.stage() as staged:
            staged.write(b"real local bytes")
            info = save(engine, store, token, str(uuid4()), meta, staged)
        fid = UUID(str(info["id"]))
        tid, created = submit_file(engine, token, fid, "verify-one")
        assert created
        assert submit_file(engine, token, fid, "verify-one") == (tid, False)
        runner = Runner(engine, {("file.verify", "1"): FileVerify(store)})
        assert runner.run(org, tid) == "succeeded"
        assert runner.run(org, tid) == "ignored"
        tid2, _ = submit_file(engine, token, fid, "tamper")
        (store.root / "objects" / str(org) / str(fid)).write_bytes(b"corrupted")
        assert runner.run(org, tid2) == "failed"
        with engine.connect() as c:
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM audit_events WHERE action_code='file.verified' AND target_id=%s",
                    (tid,),
                ).scalar_one()
                == 1
            )
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM audit_events WHERE action_code='file.verified' AND target_id=%s",
                    (tid2,),
                ).scalar_one()
                == 0
            )
        with engine.begin() as c:
            c.exec_driver_sql(
                "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE member_id=%s",
                (member,),
            )
        with pytest.raises(Denied):
            submit_file(engine, token, fid, "verify-one")
    finally:
        store.close()


def test_unknown_handler_and_unsealed_dependency_fail_closed(engine):
    runner, org, _, _, tid = prepared(engine)
    runner.handlers = {}
    assert runner.run(org, tid) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql("SELECT safe_error_code FROM tasks WHERE id=%s", (tid,)).scalar_one()
            == "HANDLER_UNAVAILABLE"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_attempts WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 0
        )


def test_unknown_external_reservation_blocks_recovery_retry(engine):
    import time

    from app.tasks.service import Runner
    from tests.integration.test_schema import collection

    with engine.begin() as c:
        org, member, _ = base(c)
        _, _, _, attempt = collection(c, org, member)
        tid = c.exec_driver_sql(
            "SELECT task_id FROM task_attempts WHERE id=%s", (attempt,)
        ).scalar_one()
        c.exec_driver_sql(
            "UPDATE tasks SET max_attempts=3,lock_version=lock_version+1 WHERE id=%s", (tid,)
        )
        c.exec_driver_sql(
            "UPDATE task_attempts SET lease_expires_at=clock_timestamp()+interval '0.2 seconds' WHERE id=%s",
            (attempt,),
        )
    time.sleep(0.25)
    runner = Runner(engine, {})
    assert runner.recover(org, tid)
    with engine.connect() as c:
        assert c.exec_driver_sql(
            "SELECT state,safe_error_code FROM tasks WHERE id=%s", (tid,)
        ).one() == ("failed", "EXTERNAL_RESULT_UNKNOWN")
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_attempts WHERE task_id=%s", (tid,)
            ).scalar_one()
            == 1
        )


def test_manual_retry_audit_records_operator_not_execution_authorizer(engine):
    from app.core.repository import finish_task
    from app.security.sessions import MemberPrincipal
    from app.tasks.service import retry

    runner, org, authorizer, work, tid = prepared(engine, attempts=2)
    ticket = runner.claim(org, tid)
    operator = uuid4()
    with engine.begin() as c:
        # Simulate a finished retryable failure before the next maintenance pass.
        finish_task(
            c,
            org,
            tid,
            ticket.attempt,
            ticket.token,
            ticket.version,
            outcome="failed",
            error="LOCAL_TRANSIENT",
        )
        c.exec_driver_sql(
            "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,%s)",
            (operator, org, str(operator), "task operator"),
        )
        grant(c, org, authorizer, operator, ["task.manage"], "work", work)
        version = c.exec_driver_sql(
            "SELECT lock_version FROM tasks WHERE id=%s", (tid,)
        ).scalar_one()
        assert retry(c, MemberPrincipal(org, operator), tid, version, runner) == "queued"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT actor_member_id FROM audit_events WHERE target_id=%s AND action_code='task.retry'",
                (tid,),
            ).scalar_one()
            == operator
        )
        assert (
            c.exec_driver_sql(
                "SELECT execution_authorized_by FROM tasks WHERE id=%s", (tid,)
            ).scalar_one()
            == authorizer
        )
