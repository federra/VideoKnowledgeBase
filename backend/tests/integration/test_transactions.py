"""Cross-connection tests commit only synthetic data in the disposable database."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.database import build_engine, transaction
from app.core.repository import VersionConflict, compare_and_swap, create_task
from tests.integration.test_schema import base, execute, prediction

pytestmark = pytest.mark.database


@pytest.fixture
def engine():
    url = os.environ.get("CIP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Run pnpm db:test for isolated PostgreSQL acceptance.")
    engine = build_engine(url)
    yield engine
    engine.dispose()


def test_two_real_transactions_only_one_cas_wins(engine):
    with engine.begin() as c:
        org, _, work = base(c)
    barrier = Barrier(2)

    def writer(value):
        try:
            with engine.begin() as c:
                barrier.wait(timeout=5)
                compare_and_swap(c, "works", org, work, 1, {"name": value})
            return "updated"
        except VersionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(writer, str(i)) for i in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == ["conflict", "updated"]


def test_concurrent_idempotency_returns_one_task(engine):
    with engine.begin() as c:
        org, member, work = base(c)
    barrier = Barrier(2)
    values = {
        "org_id": org,
        "kind": "parse",
        "handler_version": "1",
        "work_id": work,
        "requested_by": member,
        "execution_authorized_by": member,
        "idempotency_key": "race",
        "input_sha256": "b" * 64,
    }

    def writer():
        with engine.begin() as c:
            barrier.wait(timeout=5)
            return create_task(c, values)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(writer) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert results[0][0] == results[1][0]
    assert sum(created for _, created in results) == 1


def test_failed_transaction_rolls_back_business_and_deferred_error(engine):
    org = None
    with pytest.raises(Exception, match="current pointer"), transaction(engine) as c:
        org, member, work = base(c)
        execute(
            c,
            "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) "
            "VALUES (%s,%s,%s,%s,'script',%s)",
            (uuid4(), org, work, str(uuid4()), member),
        )
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM organizations WHERE id=:id"), {"id": org}
            ).scalar_one()
            == 0
        )


def test_prediction_confirmed_only_after_commit_with_real_server_time(engine):
    with engine.begin() as c:
        org, member, work = base(c)
        _, frozen = prediction(c, org, member, work)
    with engine.begin() as c:
        execute(
            c,
            "INSERT INTO prediction_events(id,org_id,prediction_id,event_kind,reason,actor_member_id,occurred_at) "
            "VALUES (%s,%s,%s,'freeze_confirmed','real commit',%s,'2000-01-01')",
            (uuid4(), org, frozen, member),
        )
        assert execute(
            c,
            "SELECT e.occurred_at>=p.frozen_at FROM prediction_events e JOIN predictions p ON p.id=e.prediction_id WHERE p.id=%s",
            (frozen,),
        ).scalar_one()


def test_restricted_login_cannot_disable_guards_or_change_epoch(engine):
    import secrets

    from psycopg import sql

    from app.core.database_roles import grant_application

    role = "cip_s04_role_" + uuid4().hex
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
    try:
        with limited.begin() as c:
            org, _member, work = base(c)
        from app.core.repository import claim_task, create_task

        with limited.begin() as c:
            ident, _ = create_task(
                c,
                {
                    "org_id": org,
                    "kind": "parse",
                    "handler_version": "1",
                    "work_id": work,
                    "requested_by": _member,
                    "execution_authorized_by": _member,
                    "idempotency_key": "restricted",
                    "input_sha256": "0" * 64,
                },
            )
            attempt, _, _ = claim_task(c, org, ident, 2)
        with pytest.raises(Exception, match="permission"), limited.begin() as c:
            execute(
                c,
                "UPDATE task_attempts SET finished_at=started_at,outcome='succeeded' WHERE id=%s",
                (attempt,),
            )
        for statement in [
            "ALTER TABLE works DISABLE TRIGGER ALL",
            "TRUNCATE works CASCADE",
            "SET session_replication_role='replica'",
            "CREATE TABLE public.bypass_guard(id int)",
            "UPDATE organizations SET authz_version=123",
        ]:
            with pytest.raises(Exception, match="permission|owner|superuser"), limited.begin() as c:
                execute(c, statement)
        with limited.begin() as c:
            compare_and_swap(c, "works", org, work, 1, {"name": "restricted edit"})
    finally:
        limited.dispose()
        with engine.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
