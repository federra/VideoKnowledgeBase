"""Real PG, synthetic public transport. Never writes provider fixtures to the project DB."""

from uuid import UUID, uuid4

import httpx
import pytest

from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def prepare(engine, setup, *, work_fields=None):
    from app.collection.novels import NovelCollect, submit
    from app.connectors.novels import VERSION, PublicNovels
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    org, member, token, *_ = setup
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            [
                "content.read",
                "source.configure",
                "collection.run",
                "evidence.read",
                "research.submit",
            ],
        )
    calls = []

    def transport(r):
        calls.append(r)
        if r.url.host == "www.qidian.com":
            return httpx.Response(202, text="challenge")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "book_list": [
                        {
                            "bookId": "123",
                            "bookName": "测试科幻",
                            "author": "某作者",
                            "abstract": "原始简介",
                            "read_count": 0,
                            "currentPos": 1,
                            **(work_fields or {}),
                        }
                    ]
                },
            },
        )

    handler = NovelCollect(
        PublicNovels(httpx.Client(transport=httpx.MockTransport(transport)), decoder={}),
        min_interval=0,
    )
    runner = Runner(engine, {("collect.novels", VERSION): handler})

    def start(
        code="fanqie:read:male:8",
        platform="fanqie",
        kind="read",
        *,
        gender="male",
        category="科幻",
        category_id="8",
    ):
        board = {
            "platform": platform,
            "rank_type": kind,
            "gender": gender,
            "category_id": category_id,
            "category_name": category,
            "rank_version": "123",
            "code": code,
            "font_sha256": "a" * 64,
        }
        with engine.begin() as c:
            return submit(c, authenticate(c, token), board, handler)

    return runner, start, calls, token


def test_novel_pipeline_filters_handoff_and_video_isolation(engine, setup):
    from app.collection.service import identity
    from app.contracts.models import ResearchEvidenceCreate
    from app.intelligence.handoff import create_handoff
    from app.intelligence.novels import feed
    from app.intelligence.service import feed as videos
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    org = setup[0]
    runner, start, calls, token = prepare(engine, setup)
    saved = start()
    assert runner.run(org, UUID(saved["task_id"])) == "succeeded"
    # Repeated operator action cannot create or spend a second same-day request.
    assert start()["task_id"] == saved["task_id"]
    with engine.begin() as c:
        p = authenticate(c, token)
        day = shanghai_date()
        result = feed(c, p, "motion_comic", day)
        assert result["total"] == "1" and result["novel_count"] == "1"
        item = result["items"][0]
        assert (
            item["reader_count"] == "0"
            and item["item"]["entry"]["observation"]["view_count"] is None
        )
        assert feed(c, p, "motion_comic", day, genre="不存在")["items"] == []
        assert feed(c, p, "story_short", day)["items"] == []
        assert videos(c, p, "motion_comic", day)["metrics"]["videos"] is None
        assert videos(c, p, "motion_comic", day)["items"] == []
        v = item["item"]
        entry = v["entry"]
        evidence = create_handoff(
            c,
            p,
            entry["id"],
            ResearchEvidenceCreate(
                business_code="motion_comic",
                business_date=day,
                snapshot_id=entry["snapshot_id"],
                snapshot_version=v["snapshot_version"],
            ),
            str(uuid4()),
        )
        assert evidence["body"]["entry"]["observation"]["platform_code"] == "fanqie"
        assert evidence["body"]["entry"]["observation"]["reader_count"] == "0"
        other = identity(
            c, "external_contents", org, "platform_content_id", "123", platform="douyin"
        )
        assert str(other) != str(evidence["body"]["content_id"])
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) SELECT gen_random_uuid(),org_id,id,1,'access_revoked','test' FROM raw_assets WHERE org_id=%s",
            (org,),
        )
        assert feed(c, p, "motion_comic", day)["items"] == []
    assert len(calls) == 1


def test_novel_qidian_failed_response_is_evidence_not_empty_success(engine, setup):
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    runner, start, calls, token = prepare(engine, setup)
    org = setup[0]
    saved = start("qidian:catalog", "qidian", "catalog")
    assert runner.run(org, UUID(saved["task_id"])) == "failed"
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM raw_assets WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
        result = feed(c, authenticate(c, token), "motion_comic", shanghai_date())
        assert result["novel_count"] is None
        assert result["statuses"][0]["http_status"] == 202
        assert result["statuses"][0]["state"] == "failed"
    assert len(calls) == 1


def test_novel_empty_snapshot_requires_its_response_access(engine, setup):
    from app.collection.novels import NovelCollect, submit
    from app.connectors.novels import VERSION, PublicNovels
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    org = setup[0]
    prepare(engine, setup)
    handler = NovelCollect(
        PublicNovels(
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"code": 0, "data": {"book_list": []}})
                )
            ),
            decoder={},
        ),
        min_interval=0,
    )
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        saved = submit(
            c,
            p,
            {
                "platform": "fanqie",
                "code": "fanqie:read:male:9",
                "rank_type": "read",
                "gender": "male",
                "category_id": "9",
                "category_name": "科幻",
                "rank_version": "123",
            },
            handler,
        )
    assert (
        Runner(engine, {("collect.novels", VERSION): handler}).run(org, UUID(saved["task_id"]))
        == "succeeded"
    )
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        assert feed(c, p, "motion_comic", shanghai_date())["novel_count"] == "0"
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) SELECT gen_random_uuid(),org_id,id,1,'access_revoked','test' FROM raw_assets WHERE org_id=%s",
            (org,),
        )
        result = feed(c, p, "motion_comic", shanghai_date())
        assert result["novel_count"] is None and result["genres"] == []


def test_novel_inline_tasks_are_not_dispatched_or_claimed_by_common_worker(
    engine, setup, monkeypatch
):
    from app.tasks import worker
    from app.tasks.service import Runner, sweep

    org = setup[0]
    runner, start, calls, _ = prepare(engine, setup)
    saved = start()
    common = Runner(engine, {})
    sent = []
    sweep(common, lambda o, t: sent.append((o, t)))
    assert (org, UUID(saved["task_id"])) not in sent
    monkeypatch.setattr(worker, "runtime", lambda: common)
    worker.execute(str(org), saved["task_id"])
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT state FROM tasks WHERE org_id=%s AND id=%s", (org, UUID(saved["task_id"]))
            ).scalar_one()
            == "queued"
        )
    assert runner.run(org, UUID(saved["task_id"])) == "succeeded" and len(calls) == 1


@pytest.mark.parametrize(
    "fields,expected_gender,expected_genre",
    [
        ({}, None, None),
        ({"gender": "female", "categoryV2": "科幻"}, "female", "科幻"),
        ({"category": "都市"}, None, None),
    ],
)
def test_novel_work_classification_uses_raw_fields_not_board(
    engine, setup, fields, expected_gender, expected_genre
):
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    runner, start, calls, token = prepare(engine, setup, work_fields=fields)
    saved = start()
    assert runner.run(setup[0], UUID(saved["task_id"])) == "succeeded"
    with engine.begin() as c:
        result = feed(c, authenticate(c, token), "motion_comic", shanghai_date())
        book = result["items"][0]
        assert book["board"]["gender"] == "male" and book["board"]["category_name"] == "科幻"
        assert book["work_gender"] == expected_gender and book["work_genre"] == expected_genre
    assert len(calls) == 1


def test_novel_fanqie_gender_genre_dependencies_keep_four_rank_dimensions(engine, setup):
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    runner, start, _, token = prepare(engine, setup)
    for kind in ("read", "new"):
        for gender, cat, cid in [
            ("male", "科幻末世", "8"),
            ("female", "科幻末世", "8"),
            ("male", "都市高武", "1014"),
            ("female", "宫斗宅斗", "246"),
        ]:
            saved = start(
                f"fanqie:{kind}:{gender}:{cid}",
                kind=kind,
                gender=gender,
                category=cat,
                category_id=cid,
            )
            assert runner.run(setup[0], UUID(saved["task_id"])) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, token)
        result = feed(c, p, "motion_comic", shanghai_date(), platform="fanqie")
        assert {r["value"] for r in result["rank_types"]} == {"read", "new"}
        assert {r["value"] for r in result["genders"]} == {"male", "female"}
        assert all(not r.get("disabled", False) for r in result["genres"])
        male = feed(
            c,
            p,
            "motion_comic",
            shanghai_date(),
            platform="fanqie",
            gender="male",
            rank_type="new",
            q="no matching book",
        )
        categories = {r["value"]: r for r in male["genres"]}
        assert categories["宫斗宅斗"].get("disabled") is True
        assert categories["宫斗宅斗"].get("reason")
        assert not categories["科幻末世"].get("disabled", False)
        assert not categories["都市高武"].get("disabled", False)
        female = feed(c, p, "motion_comic", shanghai_date(), platform="fanqie", gender="female")
        assert next(r for r in female["genres"] if r["value"] == "都市高武").get("disabled") is True
        assert (
            feed(
                c,
                p,
                "motion_comic",
                shanghai_date(),
                platform="fanqie",
                gender="male",
                genre="宫斗宅斗",
            )["total"]
            == "0"
        )
