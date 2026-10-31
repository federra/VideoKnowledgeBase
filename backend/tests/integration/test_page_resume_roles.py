"""New provenance guards must work through the genuine restricted SQL role."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import event

from app.core.database import build_engine
from app.core.database_roles import grant_application

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


@contextmanager
def restricted(owner):
    """Owner provisions only; all application connections switch current_user."""
    role = "cip_resume_test_" + uuid4().hex
    with owner.begin() as c:
        cursor = c.connection.driver_connection.cursor()
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role))
        )
        grant_application(cursor, role)
    app = build_engine(owner.url)

    @event.listens_for(app, "connect")
    def switch_role(dbapi_connection, _):
        with dbapi_connection.cursor() as cursor:
            cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        dbapi_connection.commit()

    try:
        with app.connect() as c:
            assert c.exec_driver_sql("SELECT current_user").scalar_one() == role
            assert not c.exec_driver_sql(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).scalar_one()
            assert not c.exec_driver_sql(
                "SELECT pg_has_role(current_user,tableowner,'MEMBER') FROM pg_tables WHERE schemaname='public' AND tablename='tasks'"
            ).scalar_one()
        yield app
    finally:
        app.dispose()
        with owner.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def assert_function_privileges(c):
    for signature in (
        "cip_page_reuse_allowed(uuid,uuid,uuid)",
        "cip_hongguo_saved_allowed(uuid,uuid,uuid)",
    ):
        assert c.exec_driver_sql(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (signature,)
        ).scalar_one()
    for signature in ("cip_validate()", "cip_task_guard()", "cip_runtime_guard()"):
        # A future rename must not silently weaken this assertion.
        assert not c.exec_driver_sql(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (signature,)
        ).scalar_one()


def test_saved_hongguo_complete_flow_and_feed_as_restricted_role(engine, setup):
    from tests.integration.test_hongguo_saved import (
        test_saved_hongguo_manual_time_idempotency_and_zero_calls,
    )

    with restricted(engine) as app:
        test_saved_hongguo_manual_time_idempotency_and_zero_calls(app, setup)
        with app.connect() as c:
            assert_function_privileges(c)


def test_microfilm_resume_complete_flow_feed_and_comment_trace_as_restricted_role(engine, setup):
    from tests.integration.test_page_resume import (
        test_resume_reuses_completed_comment_sample_and_latest_manifest,
    )

    with restricted(engine) as app:
        test_resume_reuses_completed_comment_sample_and_latest_manifest(app, setup)
        with app.connect() as c:
            assert_function_privileges(c)
