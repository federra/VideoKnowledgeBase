"""Browser captures must publish only through exact frozen local provenance."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from tests.test_qidian_browser import capture

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def current_capture():
    d = json.loads(capture())
    d["captured_at"] = datetime.now(UTC).isoformat()
    return json.dumps(d, ensure_ascii=False)


def test_browser_qidian_preserves_capture_provenance_and_revocation(engine, setup):
    from app.collection.qidian_browser import run_browser, submit_browser
    from app.connectors.qidian_browser import discover
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import TaskError
    from tests.integration.test_novels import prepare

    prepare(engine, setup)
    body = current_capture()
    board = discover(body)[0]
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        saved = submit_browser(c, p, board, body)
        assert submit_browser(c, p, board, body) == saved
        with pytest.raises(TaskError):
            submit_browser(c, p, board, body.replace("真实简介", "不同简介"))
    assert run_browser(engine, setup[0], UUID(saved["task_id"]))["task_state"] == "succeeded"
    assert run_browser(engine, setup[0], UUID(saved["task_id"])) == {
        "run_outcome": "ignored",
        "task_state": "succeeded",
    }
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        result = feed(c, p, "motion_comic", shanghai_date(), platform="qidian", gender="female")
        assert result["total"] == "1" and result["items"][0]["reader_count"] is None
        assert result["items"][0]["board"]["method"] == "qidian-browser-ax-v1"
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
        raw = (
            c.exec_driver_sql(
                "SELECT origin,body_text FROM raw_assets WHERE org_id=%s", (setup[0],)
            )
            .mappings()
            .one()
        )
        assert raw["origin"] == "manual" and raw["body_text"] == body
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) SELECT gen_random_uuid(),org_id,id,1,'access_revoked','test' FROM raw_assets WHERE org_id=%s",
            (setup[0],),
        )
        assert feed(c, p, "motion_comic", shanghai_date(), platform="qidian")["items"] == []


def test_browser_capture_cannot_use_saved_html_contract_or_stale_date(engine, setup):
    from app.collection.qidian_browser import submit_browser
    from app.connectors.qidian_browser import discover
    from app.connectors.redfox import AdapterError
    from app.security.sessions import authenticate
    from app.tasks.service import TaskError
    from tests.integration.test_novels import prepare

    prepare(engine, setup)
    body = current_capture()
    board = discover(body)[0]
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        bad = {**board, "method": "qidian-desktop-html-v1"}
        with pytest.raises(TaskError):
            submit_browser(c, p, bad, body)
        d = json.loads(body)
        d["captured_at"] = "2020-01-01T00:00:00+00:00"
        with pytest.raises((TaskError, AdapterError)):
            submit_browser(c, p, board, json.dumps(d))
