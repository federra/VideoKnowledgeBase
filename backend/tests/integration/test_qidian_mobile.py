"""Qidian-only collection and read projection; no live provider calls."""

from uuid import UUID

import httpx
import pytest

from tests.test_qidian_mobile import board, page

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_qidian_capture_taxonomy_and_missing_metrics_do_not_change_fanqie(engine, setup):
    from app.collection.novels import submit
    from app.collection.qidian_mobile import QidianCollect
    from app.connectors.novels import VERSION
    from app.connectors.qidian_mobile import QidianMobile
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner
    from tests.integration.test_novels import prepare

    org, _member, token, *_ = setup
    fanqie_runner, fanqie_start, fanqie_calls, _ = prepare(
        engine, setup, work_fields={"category": "都市"}
    )
    fanqie = fanqie_start()
    assert fanqie_runner.run(org, UUID(fanqie["task_id"])) == "succeeded"
    html = (
        page()
        .replace('"text": "玄幻", "value": 21', '"text": "都市", "value": 4')
        .replace('"cat": "玄幻"', '"cat": "都市"')
    )
    calls = []

    def transport(r):
        calls.append(r)
        return httpx.Response(200, text=html)

    handler = QidianCollect(
        QidianMobile(httpx.Client(transport=httpx.MockTransport(transport))), min_interval=0
    )
    with engine.begin() as c:
        p = authenticate(c, token)
        saved = submit(c, p, board(), handler)
    runner = Runner(engine, {("collect.novels", VERSION): handler})
    assert runner.run(org, UUID(saved["task_id"])) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, token)
        result = feed(c, p, "motion_comic", shanghai_date())
        q = next(x for x in result["items"] if x["board"]["platform"] == "qidian")
        f = next(x for x in result["items"] if x["board"]["platform"] == "fanqie")
        assert q["reader_count"] is None and q["work_gender"] is None and q["work_genre"] == "都市"
        assert (
            f["work_genre"] is None
        )  # Qidian taxonomy must never fill legacy Fanqie parent genre.
        assert {"value": "yuepiao", "label": "月票榜"} in result["rank_types"]
        assert (
            feed(c, p, "motion_comic", shanghai_date(), platform="qidian", genre="都市")["total"]
            == "1"
        )
        assert (
            feed(c, p, "motion_comic", shanghai_date(), platform="fanqie", genre="都市")["total"]
            == "0"
        )
        assert submit(c, p, board(), handler)["task_id"] == saved["task_id"]
    assert len(calls) == 1 and len(fanqie_calls) == 1
    # Another response must not borrow the successful board's taxonomy.
    other = {**board(), "rank_type": "rec", "rank_name": "推荐榜", "code": "qidian:mobile:male:rec"}
    mismatched = (
        page()
        .replace('"cat": "玄幻"', '"cat": "都市"')
        .replace('"bid": "123"', '"bid": "456"')
        .replace('"pageType": "yuepiao"', '"pageType": "rec"')
    )
    handler2 = QidianCollect(
        QidianMobile(
            httpx.Client(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, text=mismatched))
            )
        ),
        min_interval=0,
    )
    with engine.begin() as c:
        p = authenticate(c, token)
        other_saved = submit(c, p, other, handler2)
    assert (
        Runner(engine, {("collect.novels", VERSION): handler2}).run(
            org, UUID(other_saved["task_id"])
        )
        == "succeeded"
    )
    with engine.begin() as c:
        p = authenticate(c, token)
        rows = feed(c, p, "motion_comic", shanghai_date(), platform="qidian")
        wrong = next(x for x in rows["items"] if x["board"]["rank_type"] == "rec")
        assert wrong["work_genre"] is None
        assert (
            feed(c, p, "motion_comic", shanghai_date(), platform="qidian", genre="都市")["total"]
            == "1"
        )


def test_qidian_failed_female_catalog_is_visible_disabled_not_fake_success(engine, setup):
    from app.collection.novels import submit
    from app.collection.qidian_mobile import QidianCollect
    from app.connectors.novels import VERSION
    from app.connectors.qidian_mobile import METHOD, QidianMobile
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner
    from tests.integration.test_novels import prepare

    prepare(engine, setup)
    handler = QidianCollect(
        QidianMobile(
            httpx.Client(
                transport=httpx.MockTransport(lambda r: httpx.Response(202, text="challenge"))
            )
        ),
        min_interval=0,
    )
    b = {
        "platform": "qidian",
        "method": METHOD,
        "rank_type": "catalog",
        "gender": "female",
        "code": "qidian:mobile:female:catalog",
    }
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        saved = submit(c, p, b, handler)
    assert (
        Runner(engine, {("collect.novels", VERSION): handler}).run(setup[0], UUID(saved["task_id"]))
        == "failed"
    )
    with engine.begin() as c:
        r = feed(c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), platform="qidian")
        female = next(x for x in r["genders"] if x["value"] == "female")
        assert female["disabled"] is True and "202" in female["reason"]
        assert r["total"] == "0" and not r["items"]
