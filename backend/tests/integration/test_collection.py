"""Real PG collection pipeline; provider HTTP is synthetic and separately labelled."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import httpx
import pytest

from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def payload(likes=0):
    return {
        "code": 2000,
        "data": {
            "list": [
                {
                    "videoId": "stable-content",
                    "authorUid": "stable-author",
                    "content": "description only",
                    "opusUrl": "https://www.douyin.com/video/123",
                    "publishTime": "2026-10-16 12:30:00",
                    "likeCount": likes,
                    "duration": 1234,
                }
            ]
        },
    }


def prepared(engine, setup, *, response=None, before=None):
    from app.collection.handler import Collect
    from app.collection.service import configure_connection, configure_source, submit
    from app.connectors.redfox import VERSION, RedFox
    from app.contracts.models import CollectionCreate
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    org, member, token, *_ = setup
    calls = []
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
                "task.read",
                "task.manage",
            ],
        )
        p = authenticate(c, token)
        connection = configure_connection(c, p, "redfox test")
        source = configure_source(c, p, "creator", "account", "stable-author", enabled=True)

    def transport(request):
        calls.append(request)
        if before:
            before()
        return response(request) if response else httpx.Response(200, json=payload())

    handler = Collect(
        RedFox(lambda: "dummy-key", transport=httpx.MockTransport(transport)), min_interval=0
    )
    runner = Runner(engine, {("collect.redfox", VERSION): handler})
    request = CollectionCreate(
        source_id=source, provider_connection_id=connection, capability_code="douyin.creator.works"
    )

    def start(key=None):
        with engine.begin() as c:
            return submit(c, authenticate(c, token), request, str(key or uuid4()), handler)

    return runner, start, org, member, source, connection, request, calls, token


def task_id(accepted):
    from uuid import UUID

    return UUID(accepted["task"]["task_id"])


def test_real_pipeline_saves_call_evidence_identity_observation_snapshot_and_task_atomically(
    engine, setup
):
    runner, start, org, _, _, _, _, calls, _ = prepared(engine, setup)
    accepted = start()
    assert runner.run(org, task_id(accepted)) == "succeeded"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
        assert c.exec_driver_sql(
            "SELECT outcome,returned_items FROM collection_calls WHERE org_id=%s", (org,)
        ).one() == ("success", 1)
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
            == 1
        )
        assert c.exec_driver_sql(
            "SELECT like_count,view_count,duration_ms,published_at FROM content_observations WHERE org_id=%s",
            (org,),
        ).one() == (0, None, 1234, None)
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_outputs WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
    assert len(calls) == 1


def test_same_key_and_duplicate_delivery_cannot_spend_or_publish_twice(engine, setup):
    runner, start, org, _, _, _, _, calls, _ = prepared(engine, setup)
    key = uuid4()
    accepted = start(key)
    replay = start(key)
    assert replay["resource_id"] == accepted["resource_id"]
    assert replay["reused_existing_task"] is True
    assert accepted["reused_existing_task"] is False
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=5)
        return runner.run(org, task_id(accepted))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == ["ignored", "succeeded"]
    assert start(key)["task"]["state"] == "succeeded"
    assert runner.run(org, task_id(accepted)) == "ignored" and len(calls) == 1


def test_new_connection_preserves_same_identity_but_distinct_history(engine, setup):
    from app.collection.service import configure_connection, submit
    from app.security.sessions import authenticate

    runner, start, org, _, source, _, request, calls, token = prepared(engine, setup)
    first = start()
    assert runner.run(org, task_id(first)) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, token)
        second_connection = configure_connection(c, p, "redfox explicit second connection")
        second = submit(
            c,
            p,
            request.model_copy(update={"provider_connection_id": second_connection}),
            str(uuid4()),
            next(iter(runner.handlers.values())),
        )
    assert runner.run(org, task_id(second)) == "succeeded"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM external_contents WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM content_observations WHERE org_id=%s", (org,)
            ).scalar_one()
            == 2
        )
        assert c.exec_driver_sql(
            "SELECT array_agg(version_no ORDER BY version_no) FROM intelligence_snapshots WHERE source_id=%s",
            (source,),
        ).scalar_one() == [1, 2]
        assert (
            c.exec_driver_sql(
                "SELECT count(DISTINCT connection_id) FROM collection_jobs WHERE org_id=%s", (org,)
            ).scalar_one()
            == 2
        )
    assert len(calls) == 2


@pytest.mark.parametrize(
    "status,body,error",
    [
        (429, {}, "RATE_LIMITED"),
        (410, {}, "SOURCE_UNAVAILABLE"),
        (200, {"code": 3203}, "SOURCE_UNAVAILABLE"),
        (200, {"code": 2000, "data": {"list": [{}]}}, "INVALID_RESPONSE"),
    ],
)
def test_known_failures_keep_evidence_without_success_snapshot_or_auto_retry(
    engine, setup, status, body, error
):
    runner, start, org, _, _, _, _, calls, _ = prepared(
        engine, setup, response=lambda r: httpx.Response(status, json=body)
    )
    accepted = start()
    assert runner.run(org, task_id(accepted)) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE id=%s", (task_id(accepted),)
            ).scalar_one()
            == error
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM raw_assets WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
    assert len(calls) == 1


def test_empty_provider_success_is_real_zero_snapshot(engine, setup):
    runner, start, org, *_ = prepared(
        engine,
        setup,
        response=lambda r: httpx.Response(200, json={"code": 2000, "data": {"list": []}}),
    )
    accepted = start()
    assert runner.run(org, task_id(accepted)) == "succeeded"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT entry_count FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )


def test_revoke_during_network_retains_call_evidence_but_no_formal_result(engine, setup):
    org, member, *_ = setup

    def revoke():
        with engine.begin() as c:
            c.exec_driver_sql(
                "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s",
                (org, member),
            )

    runner, start, org, _, _, _, _, calls, _ = prepared(engine, setup, before=revoke)
    accepted = start()
    assert runner.run(org, task_id(accepted)) == "failed"
    with engine.connect() as c:
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
        assert (
            c.exec_driver_sql(
                "SELECT outcome FROM collection_calls WHERE org_id=%s", (org,)
            ).scalar_one()
            == "success"
        )
    assert len(calls) == 1


def test_budget_source_and_configuration_are_checked_before_network(engine, setup):
    from app.collection.service import submit
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    runner, start, org, _, source, _, request, calls, token = prepared(engine, setup)
    accepted = start()
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE sources SET enabled=false,lock_version=lock_version+1 WHERE id=%s", (source,)
        )
    assert runner.run(org, task_id(accepted)) == "failed" and calls == []
    with pytest.raises(Denied), engine.begin() as c:
        submit(
            c,
            authenticate(c, token),
            request.model_copy(update={"max_requests": 2}),
            str(uuid4()),
            next(iter(runner.handlers.values())),
        )


def test_local_rate_limit_prevents_second_paid_reservation(engine, setup):
    runner, start, org, _, _, _, _, calls, _ = prepared(engine, setup)
    handler = next(iter(runner.handlers.values()))
    handler.min_interval = 60
    first = start()
    assert runner.run(org, task_id(first)) == "succeeded"
    second = start()
    assert runner.run(org, task_id(second)) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE id=%s", (task_id(second),)
            ).scalar_one()
            == "RATE_LIMITED"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
    assert len(calls) == 1


def test_collection_network_unknown_never_retries(engine, setup):
    def unavailable(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    runner, start, org, _, _, _, _, calls, _ = prepared(engine, setup, response=unavailable)
    job = start()
    assert runner.run(org, task_id(job)) == "failed"
    assert runner.run(org, task_id(job)) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE id=%s", (task_id(job),)
            ).scalar_one()
            == "EXTERNAL_RESULT_UNKNOWN"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
    assert len(calls) == 1


def test_collection_cross_day_keeps_evidence_without_today_snapshot(engine, setup):
    from dataclasses import replace
    from datetime import timedelta

    runner, start, org, _, _, _, _, calls, _ = prepared(engine, setup)
    connector = next(iter(runner.handlers.values())).connector
    original = connector.fetch

    def next_day(*args, **kwargs):
        reply = original(*args, **kwargs)
        return replace(reply, captured_at=reply.captured_at + timedelta(days=1))

    connector.fetch = next_day
    job = start()
    assert runner.run(org, task_id(job)) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE id=%s", (task_id(job),)
            ).scalar_one()
            == "DATE_WINDOW_MISMATCH"
        )
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
    assert len(calls) == 1


def test_collection_stale_lease_cannot_publish_but_late_evidence_is_saved(engine, setup):
    def expire():
        with engine.begin() as c:
            c.exec_driver_sql(
                "UPDATE task_attempts SET lease_expires_at=started_at+interval '1 microsecond' WHERE org_id=%s AND finished_at IS NULL",
                (setup[0],),
            )

    runner, start, org, _, _, _, _, calls, _ = prepared(engine, setup, before=expire)
    job = start()
    assert runner.run(org, task_id(job)) == "ignored"
    assert runner.recover(org, task_id(job))
    with engine.connect() as c:
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
    assert len(calls) == 1


def test_collection_start_http_contract_csrf_budget_and_current_state(engine, setup, monkeypatch):
    from fastapi.testclient import TestClient

    import app.collection.http as route
    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for

    runner, _, org, _, _, _, request, calls, token = prepared(engine, setup)
    monkeypatch.setattr(route, "registry", lambda: runner.handlers)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        with TestClient(app, base_url="http://localhost:8000") as client:
            client.cookies.set("cip_session", token, path="/api/v1")
            headers = {
                "X-CSRF-Token": csrf_for(token),
                "Idempotency-Key": str(uuid4()),
                "Origin": "http://localhost:5173",
            }
            body = request.model_dump(mode="json")
            assert client.post("/api/v1/collection-jobs", json=body).status_code == 403
            assert (
                client.post(
                    "/api/v1/collection-jobs", json={**body, "max_requests": 2}, headers=headers
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/v1/collection-jobs", content=b"x" * 16385, headers=headers
                ).status_code
                == 413
            )
            first = client.post("/api/v1/collection-jobs", json=body, headers=headers)
            assert first.status_code == 202, first.text
            assert calls == []
            value = first.json()["data"]
            assert runner.run(org, task_id(value)) == "succeeded"
            replay = client.post("/api/v1/collection-jobs", json=body, headers=headers)
            assert replay.json()["data"]["task"]["state"] == "succeeded"
            conflict = client.post(
                "/api/v1/collection-jobs", json={**body, "max_items": 2}, headers=headers
            )
            assert conflict.status_code == 409
    finally:
        app.dependency_overrides.clear()
    assert len(calls) == 1


def test_collection_account_search_is_bounded_and_missing_counts_stay_unknown(engine, setup):
    from app.collection.service import configure_source, submit
    from app.security.sessions import authenticate

    response = {
        "code": 2000,
        "data": {
            "list": [
                {"uid": str(n), "nickname": "same name", "followerCount": 0} for n in range(20)
            ]
        },
    }
    runner, _, org, _, _, _, request, calls, token = prepared(
        engine, setup, response=lambda r: httpx.Response(200, json=response)
    )
    with engine.begin() as c:
        p = authenticate(c, token)
        source = configure_source(c, p, "search", "keyword", "漫剧", enabled=True)
        request = request.model_copy(
            update={"source_id": source, "capability_code": "douyin.account.search", "max_items": 3}
        )
        job = submit(c, p, request, str(uuid4()), next(iter(runner.handlers.values())))
    assert runner.run(org, task_id(job)) == "succeeded"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT entry_count FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 3
        )
        assert (
            c.exec_driver_sql(
                "SELECT returned_items FROM collection_calls WHERE org_id=%s", (org,)
            ).scalar_one()
            == 20
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM account_observations WHERE org_id=%s AND follower_count=0 AND work_count IS NULL",
                (org,),
            ).scalar_one()
            == 3
        )
    assert len(calls) == 1


def test_collection_multiple_works_share_author_alias_evidence_once(engine, setup):
    from app.collection.service import submit
    from app.security.sessions import authenticate

    body = payload()
    first = body["data"]["list"][0]
    first.update(authorUniqueId="creator-name", authorShortId="123", authorSecUid="creator-sec")
    body["data"]["list"].append({**first, "videoId": "stable-content-2"})
    runner, _, org, _, _, _, request, calls, token = prepared(
        engine, setup, response=lambda r: httpx.Response(200, json=body)
    )
    with engine.begin() as c:
        job = submit(
            c,
            authenticate(c, token),
            request.model_copy(update={"max_items": 2}),
            str(uuid4()),
            next(iter(runner.handlers.values())),
        )
    assert runner.run(org, task_id(job)) == "succeeded"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT entry_count FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 2
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM external_account_aliases WHERE org_id=%s", (org,)
            ).scalar_one()
            == 3
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM content_observations WHERE org_id=%s", (org,)
            ).scalar_one()
            == 2
        )
    assert len(calls) == 1
