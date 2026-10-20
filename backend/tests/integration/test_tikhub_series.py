"""One real-PG capture with synthetic HTTP; no supplier traffic."""

import json
from uuid import UUID, uuid4

import httpx
import pytest

from tests.integration.test_collection import prepared

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_series_capture_seals_one_response_and_replay_does_not_spend(engine, setup):
    from app.collection.series import CaptureSeries, submit_capture
    from app.connectors.tikhub_series import VERSION, Series
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    *_, token = prepared(engine, setup)
    calls = []

    def transport(request):
        calls.append(request)
        from tests.test_tikhub_series import payload

        return httpx.Response(200, json=payload())

    handler = CaptureSeries(
        Series(lambda: "offline", transport=httpx.MockTransport(transport)), min_interval=0
    )
    key = str(uuid4())
    with engine.begin() as c:
        p = authenticate(c, token)
        result = submit_capture(c, p, key, handler)
    runner = Runner(engine, {("collect.tikhub-series", VERSION): handler})
    assert runner.run(p.org_id, UUID(result["task_id"])) == "succeeded"
    assert runner.run(p.org_id, UUID(result["task_id"])) == "ignored"
    assert len(calls) == 1
    with engine.begin() as c:
        assert submit_capture(c, p, key, handler) == result
        raw = c.exec_driver_sql(
            "SELECT body_text FROM raw_assets WHERE collection_job_id=%s", (UUID(result["job_id"]),)
        ).scalar_one()
        assert len(json.loads(raw)["data"]["card_list"]) == 12
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE job_id=%s",
                (UUID(result["job_id"]),),
            ).scalar_one()
            == 0
        )

    from app.collection.series import NormalizeSeries, submit_normalization
    from app.contracts.models import IntelligenceFeed
    from app.intelligence.service import feed, shanghai_date

    with engine.begin() as c:
        raw_id = c.exec_driver_sql(
            "SELECT id FROM raw_assets WHERE collection_job_id=%s", (UUID(result["job_id"]),)
        ).scalar_one()
        c.exec_driver_sql(
            "UPDATE sources SET enabled=false,lock_version=lock_version+1 WHERE id=%s",
            (UUID(result["source_id"]),),
        )
        tid = submit_normalization(c, p, raw_id)
    mapper = Runner(engine, {("series.normalize", VERSION): NormalizeSeries()})
    assert mapper.run(p.org_id, tid) == "succeeded"
    assert len(calls) == 1
    with engine.begin() as c:
        data = feed(c, p, "motion_comic", shanghai_date())
        assert data["total"] == "10" and data["keyword_ranking_status"] == "series_order"
        assert data["items"][0]["entry"]["observation"]["display_name"] == "短剧0"
        assert data["items"][0]["entry"]["observation"]["description"] == "完整剧情简介0\n第二段"
        assert data["items"][0]["entry"]["observation"]["like_count"] is None
        assert IntelligenceFeed.model_validate(data).keyword_ranking_status == "series_order"
        assert submit_normalization(c, p, raw_id) == tid
        assert feed(c, p, "motion_comic", shanghai_date(), "creator")["items"] == []
