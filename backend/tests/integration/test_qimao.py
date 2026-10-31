"""Isolated PG only: real task publication, filtered read, metadata and authorization."""

from uuid import UUID, uuid4

import httpx
import pytest

from tests.integration.test_security import grant
from tests.test_qimao import page

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_qimao_pipeline_filters_heat_calendar_and_auth(engine, setup):
    from app.collection.novels import submit
    from app.collection.qimao import QimaoCollect
    from app.connectors.novels import VERSION
    from app.connectors.qimao import Qimao, boards
    from app.intelligence.calendar import calendar
    from app.intelligence.novel_contracts import NovelFeed
    from app.intelligence.novels import feed
    from app.intelligence.service import feed as video_feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    org, member, token, *_ = setup
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            ["content.read", "source.configure", "collection.run", "evidence.read"],
        )
    calls = []

    def transport(req):
        calls.append(str(req.url))
        female = "/girl/" in str(req.url)
        html = page(channel="girl" if female else "boy")
        if female:
            html = (
                html.replace("/shuku/1/", "/shuku/101/")
                .replace("/shuku/2/", "/shuku/102/")
                .replace("都市高武", "总裁豪门")
                .replace("都市", "现代言情")
            )
        return httpx.Response(200, text=html)

    handler = QimaoCollect(Qimao(httpx.Client(transport=httpx.MockTransport(transport))))
    handler.min_interval = 0  # Synthetic transport, no real public requests in PG tests.
    runner = Runner(engine, {("collect.novels", VERSION): handler})
    saved = []
    for board in [b for b in boards() if b["rank_type"] == "hot"]:
        with engine.begin() as c:
            p = authenticate(c, token)
            ticket = submit(c, p, board, handler)
        assert runner.run(org, UUID(ticket["task_id"])) == "succeeded"
        saved.append(ticket)
        with engine.begin() as c:
            # Same day key does not create a second request or job.
            assert submit(c, p, board, handler) == ticket
    assert len(calls) == 2
    with engine.begin() as c:
        p = authenticate(c, token)
        today = shanghai_date()
        all_ = NovelFeed.model_validate(feed(c, p, "motion_comic", today, platform="qimao"))
        assert all_.total == "4" and all_.novel_count == "4"
        assert {x.value for x in all_.genders} == {"male", "female"}
        assert {x.label for x in all_.genres} == {"都市", "现代言情"}
        male = feed(c, p, "motion_comic", today, platform="qimao", gender="male", genre="都市")
        assert male["total"] == "2" and male["items"][0]["work_genre"] == "都市"
        assert male["items"][0]["reader_count"] is None
        assert male["items"][0]["heat_value"] == "96000"
        assert male["items"][0]["heat_display"] == "9.6万"
        obs = male["items"][0]["item"]["entry"]["observation"]
        assert obs["heat_value"] == "96000" and obs["reader_count"] is None
        assert next(g for g in male["genres"] if g["value"] == "现代言情")["disabled"]
        assert feed(c, p, "story_short", today, platform="qimao")["total"] == "0"
        assert video_feed(c, p, "motion_comic", today)["metrics"]["videos"] is None
        assert today in calendar(c, p, "motion_comic", str(today)[:7])["dates"]
        rawid = c.exec_driver_sql(
            "SELECT id FROM raw_assets WHERE collection_job_id=%s", (UUID(saved[0]["job_id"]),)
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (%s,%s,%s,1,'withdrawn','isolated test')",
            (uuid4(), org, rawid),
        )
    with engine.begin() as c:
        p = authenticate(c, token)
        after = feed(c, p, "motion_comic", today, platform="qimao")
        assert after["total"] == "2" and {
            b["gender"] for b in (x["board"] for x in after["items"])
        } == {"female"}


@pytest.mark.parametrize("business", ["motion_comic", "story_short"])
def test_refresh_without_qimao_specs_does_not_advertise_unexecuted_channel(engine, setup, business):
    from app.intelligence.refresh import latest, start
    from app.security.sessions import authenticate

    org, member, token, *_ = setup
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            ["content.read", "source.configure", "collection.run", "evidence.read", "task.read"],
        )
    with engine.begin() as c:
        p = authenticate(c, token)
        task = start(c, p, business, str(uuid4()))
        view = latest(c, p, business, UUID(task["task_id"]))
        assert "qimao" not in {v["code"] for v in view["channels"]}
