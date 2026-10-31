"""Calendar reflects visible snapshots, never the existence of collection attempts."""

from uuid import UUID

import pytest

from tests.integration.test_novels import prepare

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_calendar_uses_visible_nonempty_latest_snapshot_and_business(engine, setup):
    from app.intelligence.calendar import calendar
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    runner, start, calls, token = prepare(engine, setup)
    today = shanghai_date()
    month = today.strftime("%Y-%m")
    with engine.begin() as c:
        p = authenticate(c, token)
        assert calendar(c, p, "motion_comic", month)["dates"] == []
    saved = start()
    assert runner.run(setup[0], UUID(saved["task_id"])) == "succeeded"
    requests = len(calls)
    with engine.begin() as c:
        p = authenticate(c, token)
        assert calendar(c, p, "motion_comic", month)["dates"] == [today]
        assert calendar(c, p, "story_short", month)["dates"] == []
        # Evidence withdrawal removes availability immediately, with no historical fallback.
        raw_id = c.exec_driver_sql(
            "SELECT id FROM raw_assets WHERE org_id=%s AND collection_job_id=(SELECT id FROM collection_jobs WHERE task_id=%s)",
            (setup[0], UUID(saved["task_id"])),
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'withdrawn','calendar test')",
            (setup[0], raw_id),
        )
        assert calendar(c, p, "motion_comic", month)["dates"] == []
    assert len(calls) == requests  # Reads must never collect.


def test_calendar_empty_capture_and_failed_capture_do_not_mark_date(engine, setup):
    from app.intelligence.calendar import calendar
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    runner, start, _, token = prepare(engine, setup, books=[])
    empty = start()
    failed = start("qidian:hotsales:all", platform="qidian", kind="hotsales")
    assert runner.run(setup[0], UUID(empty["task_id"])) == "succeeded"
    assert runner.run(setup[0], UUID(failed["task_id"])) == "failed"
    with engine.begin() as c:
        p = authenticate(c, token)
        assert calendar(c, p, "motion_comic", shanghai_date().strftime("%Y-%m"))["dates"] == []


def test_calendar_current_permission_and_month_boundary(engine, setup):
    from datetime import timedelta

    from app.intelligence.calendar import calendar
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    runner, start, _, token = prepare(engine, setup)
    saved = start()
    assert runner.run(setup[0], UUID(saved["task_id"])) == "succeeded"
    today = shanghai_date()
    previous = today.replace(day=1) - timedelta(days=1)
    with engine.begin() as c:
        p = authenticate(c, token)
        assert calendar(c, p, "motion_comic", previous.strftime("%Y-%m"))["dates"] == []
        assert calendar(c, p, "motion_comic", today.strftime("%Y-%m"))["dates"] == [today]
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s AND revoked_at IS NULL",
            (setup[0], setup[1]),
        )
    with engine.begin() as c:
        assert (
            calendar(c, authenticate(c, token), "motion_comic", today.strftime("%Y-%m"))["dates"]
            == []
        )
