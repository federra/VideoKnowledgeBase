"""Saved public HTML import must retain manual provenance and zero provider calls."""

from uuid import UUID

import pytest

from tests.test_qidian_desktop import overview, ranking

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_saved_qidian_rank_is_manual_immutable_and_zero_network(engine, setup):
    from app.collection.qidian_desktop import SavedQidian, run_saved, submit_saved
    from app.connectors.novels import VERSION
    from app.connectors.qidian_desktop import discover
    from app.intelligence.novels import feed
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner, TaskError
    from tests.integration.test_novels import prepare

    prepare(engine, setup)
    handler = SavedQidian()
    board = discover(overview())[0]
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        saved = submit_saved(c, p, board, ranking())
        assert submit_saved(c, p, board, ranking()) == saved
        with pytest.raises(TaskError):
            submit_saved(c, p, board, ranking().replace("原始简介", "不同材料"))
    runner = Runner(engine, {("collect.novels", VERSION): handler})
    assert runner.run(setup[0], UUID(saved["task_id"])) == "succeeded"
    replay = run_saved(engine, setup[0], UUID(saved["task_id"]))
    assert replay == {"run_outcome": "ignored", "task_state": "succeeded"}
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        r = feed(c, p, "motion_comic", shanghai_date(), platform="qidian", gender="female")
        from app.intelligence.novel_contracts import NovelFeed

        NovelFeed.model_validate(r)
        assert r["total"] == "1" and r["items"][0]["reader_count"] is None
        assert r["items"][0]["work_genre"] == "玄幻言情"
        assert (
            next(x for x in r["genders"] if x["value"] == "female").get("disabled", False) is False
        )
        assert r["statuses"][0]["http_status"] is None
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
        raw = (
            c.exec_driver_sql(
                "SELECT origin,submitted_by,collection_job_id,body_text FROM raw_assets WHERE org_id=%s",
                (setup[0],),
            )
            .mappings()
            .one()
        )
        assert (
            raw["origin"] == "manual"
            and raw["submitted_by"] == setup[1]
            and raw["collection_job_id"] is None
        )
        assert raw["body_text"] == ranking()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) SELECT gen_random_uuid(),org_id,id,1,'access_revoked','test' FROM raw_assets WHERE org_id=%s",
            (setup[0],),
        )
        assert feed(c, p, "motion_comic", shanghai_date(), platform="qidian")["items"] == []


def test_saved_overview_is_catalog_only_and_cannot_publish_preview_books(engine, setup):
    from app.collection.qidian_desktop import SavedQidian, submit_saved
    from app.connectors.novels import VERSION
    from app.connectors.qidian_desktop import discover
    from app.security.sessions import authenticate
    from app.tasks.service import Runner
    from tests.integration.test_novels import prepare

    prepare(engine, setup)
    with engine.begin() as c:
        saved = submit_saved(c, authenticate(c, setup[2]), discover(overview())[0], overview())
    assert (
        Runner(engine, {("collect.novels", VERSION): SavedQidian()}).run(
            setup[0], UUID(saved["task_id"])
        )
        == "failed"
    )
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
