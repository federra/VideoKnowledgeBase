"""Real Redis, prefork worker, Beat and killed-process recovery; no eager transport.

Only temporary PostgreSQL databases, unique Redis key prefixes and private files.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg import sql
from redis import Redis

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def wait_until(check, *, timeout=40):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("Real worker/Beat did not reach expected state within deadline")


def test_real_redis_beat_worker_kill_and_redelivery_are_fenced(engine, setup, tmp_path):
    from app.contracts.models import FileUploadQuery
    from app.core.database import build_engine
    from app.core.database_roles import grant_application
    from app.storage.local import LocalStore
    from app.storage.service import save
    from app.tasks.service import submit_file
    from tests.integration.test_file_storage import work
    from tests.integration.test_security import grant

    # No Redis FLUSH/PURGE: this test deletes only its random key namespace.
    redis_url = "redis://127.0.0.1:16379/15"
    redis = Redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3)
    assert redis.ping()
    prefix = "cip:test:" + uuid4().hex + ":"
    role = "cip_s054_" + uuid4().hex
    import secrets

    password = secrets.token_urlsafe(32)
    with engine.begin() as c:
        cursor = c.connection.driver_connection.cursor()
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        grant_application(cursor, role)
    limited = build_engine(engine.url.set(username=role, password=password))
    org, member, token, *_ = setup
    with engine.begin() as c:
        wid = work(c, org, member)
        grant(
            c,
            org,
            member,
            member,
            ["content.read", "content.write", "file.read", "task.read", "task.manage"],
            "work",
            wid,
        )
    store = LocalStore(tmp_path / "files")
    processes = []
    logs = []
    env = {
        **os.environ,
        "APPLICATION_DATABASE_URL": limited.url.render_as_string(hide_password=False),
        "REDIS_URL": redis_url,
        "TASK_KEY_PREFIX": prefix,
        "TASK_QUEUE": "cip.tasks.test." + uuid4().hex,
        "STORAGE_ROOT": str(tmp_path),
        "OBJC_DISABLE_INITIALIZE_FORK_SAFETY": "YES",
    }
    backend = Path(__file__).resolve().parents[2]

    def start(kind):
        handle = (tmp_path / (kind + str(len(processes)) + ".log")).open("w")
        logs.append(handle)
        command = [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.tasks.celery_app:app",
            kind,
            "--loglevel=WARNING",
        ]
        if kind == "worker":
            command += [
                "--pool=prefork",
                "--concurrency=1",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
                "--hostname=ciptest" + uuid4().hex + "@%h",
            ]
        else:
            command += [
                "--schedule",
                str(tmp_path / "beat-schedule"),
                "--pidfile",
                str(tmp_path / "beat.pid"),
            ]
        proc = subprocess.Popen(
            command, cwd=backend, env=env, stdout=handle, stderr=handle, start_new_session=True
        )
        processes.append(proc)
        return proc

    def state(tid):
        with engine.connect() as c:
            return c.exec_driver_sql("SELECT state FROM tasks WHERE id=%s", (tid,)).scalar_one()

    try:
        # Big enough to observe a running real file processor before killing its group.
        meta = FileUploadQuery(
            work_id=wid,
            expected_work_lock_version="1",
            original_name="sample.txt",
            media_type="text/plain",
        )
        with store.stage() as staged:
            for _ in range(512):
                staged.write(b"x" * 65536)
            info = save(limited, store, token, str(uuid4()), meta, staged)
        tid, _ = submit_file(limited, token, UUID(str(info["id"])), "broker-file", max_attempts=2)
        worker = start("worker")
        beat = start("beat")
        # No direct send: first task must arrive through actual Beat periodic dispatch.
        wait_until(lambda: state(tid) == "running")
        os.killpg(worker.pid, signal.SIGKILL)
        worker.wait(timeout=5)
        assert state(tid) == "running"
        # Simulate a shorter remaining lease, preserving immutable started_at and using
        # a still-future value. Recovery itself compares against actual PostgreSQL time.
        with engine.begin() as c:
            c.exec_driver_sql(
                "UPDATE task_attempts SET lease_expires_at=clock_timestamp()+interval '0.2 seconds' WHERE task_id=%s AND finished_at IS NULL",
                (tid,),
            )
        start("worker")
        wait_until(lambda: state(tid) == "succeeded", timeout=45)
        # Repeated real messages after completion cannot re-publish audit/product.
        from celery import Celery
        from kombu import Queue

        producer = Celery("test-producer", broker=redis_url)
        producer.conf.update(
            task_default_queue=env["TASK_QUEUE"],
            task_queues=(Queue(env["TASK_QUEUE"]),),
            broker_transport_options={
                "global_keyprefix": prefix,
                "socket_timeout": 3,
                "socket_connect_timeout": 3,
            },
            task_publish_retry=False,
        )
        try:
            for _ in range(3):
                producer.send_task(
                    "cip.execute", args=[str(org), str(tid)], ignore_result=True, retry=False
                )
            # Queue drains after consumer's prior reservations; facts stay singleton.
            wait_until(lambda: redis.llen(prefix + env["TASK_QUEUE"]) == 0)
        finally:
            producer.close()
        with engine.connect() as c:
            assert c.exec_driver_sql(
                "SELECT array_agg(outcome ORDER BY attempt_no) FROM task_attempts WHERE task_id=%s",
                (tid,),
            ).scalar_one() == ["lease_lost", "succeeded"]
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM audit_events WHERE target_id=%s AND action_code='file.verified'",
                    (tid,),
                ).scalar_one()
                == 1
            )
            assert (
                c.exec_driver_sql(
                    "SELECT max_external_calls FROM tasks WHERE id=%s", (tid,)
                ).scalar_one()
                == 0
            )
        assert beat.poll() is None
    finally:
        for proc in processes:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
        for handle in logs:
            handle.close()
        store.close()
        limited.dispose()
        with engine.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        keys = list(redis.scan_iter(match=prefix + "*"))
        if keys:
            redis.delete(*keys)
        redis.close()
