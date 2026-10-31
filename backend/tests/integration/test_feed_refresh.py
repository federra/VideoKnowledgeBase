"""Refresh batches use real isolated PG and fake external HTTP only."""

from uuid import UUID, uuid4

import pytest

from tests.integration.test_collection import prepared
from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def authorize(engine, setup):
    prepared(engine, setup)
    with engine.begin() as c:
        grant(
            c,
            setup[0],
            setup[1],
            setup[1],
            ["source.configure", "collection.run", "task.read", "content.read", "evidence.read"],
        )


def test_refresh_idempotency_active_coalescing_and_frozen_plan(engine, setup):
    from app.intelligence.refresh import latest, start
    from app.security.sessions import authenticate

    authorize(engine, setup)
    key = str(uuid4())
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        first = start(c, p, "motion_comic", key)
        assert start(c, p, "motion_comic", key)["task_id"] == first["task_id"]
        assert start(c, p, "motion_comic", str(uuid4()))["task_id"] == first["task_id"]
        assert latest(c, p, "motion_comic")["state"] == "queued"
        task = (
            c.exec_driver_sql("SELECT * FROM tasks WHERE id=%s", (UUID(first["task_id"]),))
            .mappings()
            .one()
        )
        assert task["max_attempts"] == 1 and task["max_external_calls"] == 0
        assert task["inputs_sealed_at"] is not None
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )


def test_refresh_no_grant_cannot_start_or_read(engine, setup):
    from app.intelligence.refresh import latest, start
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    for call in (
        lambda c, p: start(c, p, "motion_comic", str(uuid4())),
        lambda c, p: latest(c, p, "motion_comic"),
    ):
        with pytest.raises(Denied), engine.begin() as c:
            call(c, authenticate(c, setup[2]))


def test_refresh_same_day_new_batch_keeps_history_and_failed_channel_never_replaces(
    engine, setup, tmp_path, monkeypatch
):
    import httpx

    from app.collection.hongguo import CaptureHongguo, submit
    from app.connectors import hongguo
    from app.core.repository import compare_and_swap
    from app.intelligence.refresh import latest, start
    from app.intelligence.refresh_worker import runtime
    from app.intelligence.service import row, selected, shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner
    from tests.test_hongguo import html, player

    authorize(engine, setup)
    org, _, token, *_ = setup
    calls = []
    mode = {"fail": False, "batch": False}
    old_ids = set()

    def transport(request):
        calls.append(request.url.path)
        if "/rank/" in request.url.path:
            board = request.url.path.rsplit("/", 1)[-1]
            if mode["batch"] and old_ids:
                with engine.begin() as c:
                    # A channel's partially collected new snapshots stay hidden.
                    ids = {
                        s["id"]
                        for s, _ in selected(
                            c,
                            authenticate(c, token),
                            "motion_comic",
                            shanghai_date(),
                            platforms=("hongguo",),
                        )
                    }
                    assert ids == old_ids
            if mode["fail"] and board == "hot-real-drama":
                return httpx.Response(429, text="limited")
            return httpx.Response(200, text=html(board, hongguo.BOARDS[board], count=1))
        return httpx.Response(200, text=player(count=20))

    monkeypatch.setattr(hongguo, "INTERVAL", 0)
    connector = hongguo.Hongguo(
        httpx.Client(transport=httpx.MockTransport(transport)), tmp_path / "gate.json"
    )
    handler = CaptureHongguo(connector)
    runner = Runner(engine, {("collect.hongguo", hongguo.VERSION): handler})
    for board in hongguo.BOARDS:
        with engine.begin() as c:
            job = submit(c, authenticate(c, token), {"board": board}, handler)
        assert runner.run(org, UUID(job["task_id"])) == "succeeded"
        with engine.begin() as c:
            src = row(c, "sources", org, UUID(job["source_id"]))
            compare_and_swap(c, "sources", org, src["id"], src["lock_version"], {"enabled": False})
    with engine.begin() as c:
        old_ids = {
            s["id"]
            for s, _ in selected(
                c, authenticate(c, token), "motion_comic", shanghai_date(), platforms=("hongguo",)
            )
        }
        first = start(c, authenticate(c, token), "motion_comic", str(uuid4()))
    monkeypatch.setattr(hongguo, "Hongguo", lambda: connector)
    mode["batch"] = True
    before = len(calls)
    assert runtime(engine).run(org, UUID(first["task_id"])) == "succeeded"
    assert len(calls) - before == 5  # Four fixed boards + one deduplicated series page.
    with engine.begin() as c:
        p = authenticate(c, token)
        view = latest(c, p, "motion_comic")
        assert view["channels"][0]["state"] == "succeeded"
        new_ids = {
            s["id"]
            for s, _ in selected(c, p, "motion_comic", shanghai_date(), platforms=("hongguo",))
        }
        assert len(new_ids) == 4 and not new_ids.intersection(old_ids)
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM comment_evidence WHERE org_id=%s", (org,)
            ).scalar_one()
            == 15
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM sources WHERE org_id=%s AND enabled AND platform_code='hongguo'",
                (org,),
            ).scalar_one()
            == 0
        )
        old_ids = new_ids
        second = start(c, p, "motion_comic", str(uuid4()))
        assert second["task_id"] != first["task_id"]
    mode["fail"] = True
    before = len(calls)
    assert runtime(engine).run(org, UUID(second["task_id"])) == "succeeded"
    assert len(calls) - before == 2  # Stop the domain on 429, no third rank or comments.
    with engine.begin() as c:
        p = authenticate(c, token)
        assert latest(c, p, "motion_comic")["channels"][0]["state"] == "failed"
        assert {
            s["id"]
            for s, _ in selected(c, p, "motion_comic", shanghai_date(), platforms=("hongguo",))
        } == old_ids
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 9
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM sources WHERE org_id=%s AND enabled AND platform_code='hongguo'",
                (org,),
            ).scalar_one()
            == 0
        )


def test_refresh_real_http_csrf_idempotency_and_read_never_enqueue(engine, setup, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.intelligence import refresh_http
    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for

    authorize(engine, setup)
    monkeypatch.setattr(settings, "local_single_user", True)
    sent = []
    monkeypatch.setattr(refresh_http, "enqueue", lambda engine, org, tid: sent.append((org, tid)))
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
        client.cookies.set("cip_session", setup[2])
        path = "/api/v1/intelligence/refresh"
        assert client.get(path, params={"business_code": "motion_comic"}).status_code == 200
        assert sent == []
        body = {"business_code": "motion_comic"}
        assert client.post(path, json=body).status_code == 403
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": csrf_for(setup[2]),
            "Idempotency-Key": str(uuid4()),
        }
        first = client.post(path, json=body, headers=headers)
        assert first.status_code == 202, first.text
        ident = first.json()["data"]["task_id"]
        assert client.post(path, json=body, headers=headers).json()["data"]["task_id"] == ident
        sent.clear()
        assert client.get(path, params=body).json()["data"]["task_id"] == ident
        assert sent == []
        assert (
            client.post(
                path, json={**body, "business_date": "2026-01-01"}, headers=headers
            ).status_code
            == 422
        )
        monkeypatch.setattr(settings, "local_single_user", False)
        assert client.post(path, json=body, headers=headers).status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_refresh_tikhub_fanqie_qidian_use_new_jobs_and_current_catalog(engine, setup, monkeypatch):
    import json

    import httpx

    from app.collection.handler import Collect
    from app.collection.novels import NovelCollect
    from app.collection.novels import submit as submit_novel
    from app.collection.qidian_mobile import QidianCollect
    from app.collection.series import CaptureSeries, submit_capture
    from app.connectors import novels, qidian_mobile, tikhub_series
    from app.intelligence.refresh import latest, start
    from app.intelligence.refresh_worker import ChildJobs, runtime
    from app.security.sessions import authenticate
    from tests.test_novels import board as fboard
    from tests.test_qidian_mobile import board as qboard
    from tests.test_qidian_mobile import page
    from tests.test_tikhub_series import payload

    authorize(engine, setup)
    calls = []
    state = {
        "rank": {
            "rankVersion": "456",
            "rankCategoryTypeList": {
                "male": [{"id": "8", "name": "科幻末世"}],
                "female": [{"id": "9", "name": "古言"}],
            },
        }
    }

    def transport(request):
        calls.append(request)
        if request.url.host == "api.tikhub.io":
            return httpx.Response(200, json=payload())
        if request.url.host == "m.qidian.com":
            return httpx.Response(200, text=page())
        if request.url.path == "/rank":
            return httpx.Response(
                200, text="<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"
            )
        assert request.url.params["rank_version"] == "456"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "book_list": [
                        {
                            "bookId": "1234",
                            "bookName": "真实结构测试",
                            "author": "作者",
                            "abstract": "简介",
                            "read_count": "32.6万",
                            "currentPos": 1,
                        }
                    ]
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(transport))
    fanqie = novels.PublicNovels(client, decoder={})
    qidian = qidian_mobile.QidianMobile(client)
    series = tikhub_series.Series(lambda: "test-only", transport=httpx.MockTransport(transport))
    monkeypatch.setattr(ChildJobs, "wait", lambda *_: None)
    monkeypatch.setattr(
        NovelCollect,
        "__init__",
        lambda self, connector: Collect.__init__(self, connector, min_interval=0),
    )
    board = {**fboard(), "code": "fanqie:read:male:8", "name": "阅读榜"}
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        submit_capture(c, p, str(uuid4()), CaptureSeries(series, min_interval=0))
        submit_novel(
            c,
            p,
            {
                "platform": "fanqie",
                "rank_type": "catalog",
                "code": "fanqie:catalog",
                "name": "目录",
            },
            NovelCollect(fanqie),
        )
        submit_novel(c, p, board, NovelCollect(fanqie))
        submit_novel(c, p, qboard(), QidianCollect(qidian))
        c.exec_driver_sql(
            "UPDATE sources SET enabled=false,lock_version=lock_version+1 WHERE org_id=%s AND platform_code IN ('fanqie','qidian','douyin')",
            (p.org_id,),
        )
        batch = start(c, p, "motion_comic", str(uuid4()))
    monkeypatch.setattr(novels, "PublicNovels", lambda: fanqie)
    monkeypatch.setattr(qidian_mobile, "QidianMobile", lambda: qidian)
    monkeypatch.setattr(tikhub_series, "Series", lambda _: series)
    monkeypatch.setattr("app.collection.font_verification.verify_font", lambda *_, **kw: [])
    assert runtime(engine).run(setup[0], UUID(batch["task_id"])) == "succeeded"
    assert len(calls) == 4
    with engine.begin() as c:
        data = latest(c, authenticate(c, setup[2]), "motion_comic")
        result = {x["code"]: x["state"] for x in data["channels"]}
        assert result == {
            "hongguo": "unavailable",
            "tikhub": "succeeded",
            "fanqie": "succeeded",
            "qidian": "partial",
        }
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM snapshot_entries WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 12
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM sources WHERE org_id=%s AND enabled", (setup[0],)
            ).scalar_one()
            == 0
        )


def test_refresh_tasks_are_not_claimed_by_common_sweep(engine, setup):
    from app.intelligence.refresh import start
    from app.intelligence.refresh_worker import runtime
    from app.security.sessions import authenticate
    from app.tasks.service import sweep

    authorize(engine, setup)
    with engine.begin() as c:
        batch = start(c, authenticate(c, setup[2]), "motion_comic", str(uuid4()))
    sent = []
    sweep(runtime(engine), lambda org, tid: sent.append(tid))
    assert UUID(batch["task_id"]) not in sent


def test_refresh_cross_day_stops_before_any_provider_call(engine, setup, monkeypatch):
    from datetime import timedelta

    from app.intelligence import refresh_worker
    from app.intelligence.refresh import start
    from app.intelligence.service import shanghai_date
    from app.security.sessions import authenticate

    authorize(engine, setup)
    with engine.begin() as c:
        batch = start(c, authenticate(c, setup[2]), "motion_comic", str(uuid4()))
    tomorrow = shanghai_date() + timedelta(days=1)
    monkeypatch.setattr(refresh_worker, "shanghai_date", lambda: tomorrow)
    assert refresh_worker.runtime(engine).run(setup[0], UUID(batch["task_id"])) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE id=%s", (UUID(batch["task_id"]),)
            ).scalar_one()
            == "DATE_WINDOW_MISMATCH"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
