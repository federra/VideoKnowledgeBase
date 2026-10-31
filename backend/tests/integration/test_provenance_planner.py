"""Function-local planning must preserve the exact provenance/security contract."""

import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database

SIGNATURES = (
    "cip_page_reuse_allowed(uuid,uuid,uuid)",
    "cip_hongguo_saved_allowed(uuid,uuid,uuid)",
)


def catalog(c):
    return {
        signature: dict(
            c.exec_driver_sql(
                "SELECT oid,prosrc,proacl,prosecdef,provolatile,proowner,prolang,"
                "proparallel,proisstrict,proleakproof,proconfig FROM pg_proc "
                "WHERE oid=%s::regprocedure",
                (signature,),
            )
            .mappings()
            .one()
        )
        for signature in SIGNATURES
    }


def assert_planner(rows, enabled):
    for signature, row in rows.items():
        config = dict(value.split("=", 1) for value in row["proconfig"])
        assert config.get("join_collapse_limit") == ("1" if enabled else None), signature
        assert config["search_path"] == "public, pg_temp", signature


@pytest.mark.parametrize("kind", ["page", "hongguo"])
def test_planner_up_down_up_preserves_sources_security_and_session(engine, setup, kind):
    # These tests execute DDL, so reject every target except the UUID database
    # created by the dedicated isolated acceptance runner.
    assert re.fullmatch(r"cip_s04_test_[0-9a-f]{32}", engine.url.database)
    with engine.connect() as c:
        initial = catalog(c)
        assert_planner(initial, True)

    if kind == "page":
        from tests.integration.test_page_resume import (
            test_resume_reuses_completed_comment_sample_and_latest_manifest,
        )

        test_resume_reuses_completed_comment_sample_and_latest_manifest(engine, setup)
        signature = SIGNATURES[0]
        role = "collection_page_reuse"
    else:
        from tests.integration.test_hongguo_saved import (
            test_saved_hongguo_manual_time_idempotency_and_zero_calls,
        )

        test_saved_hongguo_manual_time_idempotency_and_zero_calls(engine, setup)
        signature = SIGNATURES[1]
        role = "hongguo_saved_capture"

    with engine.connect() as c:
        job, raw = c.exec_driver_sql(
            "SELECT j.id,i.raw_asset_id FROM collection_jobs j JOIN task_inputs i "
            "ON i.org_id=j.org_id AND i.task_id=j.task_id WHERE j.org_id=%s "
            "AND i.role=%s LIMIT 1",
            (setup[0], role),
        ).one()

    # Keep this same connection open and warm the function call before ALTER.
    # Each new transaction after migration must see the catalog invalidation.
    with engine.connect() as warm:
        session_limit = warm.exec_driver_sql("SHOW join_collapse_limit").scalar_one()

        def verdicts():
            query = "SELECT " + signature.split("(", 1)[0] + "(%s,%s,%s)"
            assert warm.exec_driver_sql(query, (setup[0], job, raw)).scalar_one() is True
            assert warm.exec_driver_sql(query, (setup[3], job, raw)).scalar_one() is False
            assert warm.exec_driver_sql(query, (setup[0], job, uuid4())).scalar_one() is False
            assert warm.exec_driver_sql("SHOW join_collapse_limit").scalar_one() == session_limit
            warm.commit()

        verdicts()
        cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        previous = os.environ.get("CIP_MIGRATION_URL")
        os.environ["CIP_MIGRATION_URL"] = engine.url.render_as_string(hide_password=False)
        try:
            for revision, enabled in (("0026_page_resume", False), ("head", True)):
                (command.upgrade if enabled else command.downgrade)(cfg, revision)
                with engine.connect() as c:
                    current = catalog(c)
                assert_planner(current, enabled)
                for name in SIGNATURES:
                    assert {k: v for k, v in current[name].items() if k != "proconfig"} == {
                        k: v for k, v in initial[name].items() if k != "proconfig"
                    }
                    assert [
                        v
                        for v in current[name]["proconfig"]
                        if not v.startswith("join_collapse_limit=")
                    ] == [
                        v
                        for v in initial[name]["proconfig"]
                        if not v.startswith("join_collapse_limit=")
                    ]
                verdicts()
        finally:
            command.upgrade(cfg, "head")
            if previous is None:
                os.environ.pop("CIP_MIGRATION_URL", None)
            else:
                os.environ["CIP_MIGRATION_URL"] = previous
