"""S06.2 source plans and status use real PG; external HTTP remains synthetic."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.security.errors import Denied
from app.security.sessions import authenticate
from tests.integration.test_collection import prepared, task_id

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_console_new_source_is_paused_with_plan_and_idempotent(engine, setup):
    from app.collection.console import create_source, list_sources
    from app.contracts.models import ConsoleSourceCreate

    _runner, _, _org, _, _, _, _, calls, token = prepared(engine, setup)
    body = ConsoleSourceCreate(
        name="漫剧搜索", address="漫剧", business_code="motion_comic", frequency="daily_0900"
    )
    key = str(uuid4())
    with engine.begin() as c:
        p = authenticate(c, token)
        first = create_source(c, p, body, key)
        assert (
            c.exec_driver_sql(
                "SELECT capability_code FROM collection_plans WHERE org_id=%s AND source_id=%s",
                (p.org_id, first["id"]),
            ).scalar_one()
            == "douyin.keyword.default"
        )
        again = create_source(c, p, body, key)
        assert first["id"] == again["id"] and first["enabled"] is False
        assert first["plan"]["enabled"] is False and first["plan"]["max_requests"] == 1
        result = list_sources(c, p, "motion_comic")
        assert any(row["id"] == first["id"] for row in result["items"])
    assert calls == []


def test_console_source_toggle_enforces_versions_scope_and_paid_plan(engine, setup):
    from app.collection.console import create_source, patch_source
    from app.contracts.models import ConsoleSourceCreate, SourcePatch

    _, _, _, _, _, _, _, _, token = prepared(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, token)
        source = create_source(
            c,
            p,
            ConsoleSourceCreate(name="topic", address="漫剧", business_code="motion_comic"),
            str(uuid4()),
        )
        updated = patch_source(
            c,
            p,
            source["id"],
            SourcePatch(expected_lock_version=source["lock_version"], enabled=True),
            str(uuid4()),
        )
        assert updated["enabled"] and updated["plan"]["enabled"]
    with pytest.raises(Denied, match="VERSION_CONFLICT"), engine.begin() as c:
        patch_source(
            c,
            authenticate(c, token),
            source["id"],
            SourcePatch(expected_lock_version=source["lock_version"], enabled=False),
            str(uuid4()),
        )


def test_console_schedule_latest_slot_no_catchup_storm_and_no_duplicate(engine, setup):
    from app.collection.console import create_source, patch_source
    from app.collection.schedule import due_slot, schedule
    from app.contracts.models import ConsoleSourceCreate, SourcePatch

    runner, _, org, _, _, _, _, calls, token = prepared(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, token)
        source = create_source(
            c,
            p,
            ConsoleSourceCreate(
                name="schedule",
                address="uid:stable-author",
                business_code="motion_comic",
                frequency="every_2h",
            ),
            str(uuid4()),
        )
        patch_source(
            c,
            p,
            source["id"],
            SourcePatch(expected_lock_version=source["lock_version"], enabled=True),
            str(uuid4()),
        )
        created = c.exec_driver_sql(
            "SELECT created_at FROM collection_plans WHERE id=%s", (source["plan"]["id"],)
        ).scalar_one()
    now = created + timedelta(hours=2)
    # Pure slot arithmetic explicitly uses Shanghai regardless of worker timezone.
    assert (
        due_slot("daily_0900", datetime(2026, 10, 17, 2, tzinfo=UTC)).isoformat()
        == "2026-10-17T01:00:00+00:00"
    )
    count = schedule(runner, now=now)
    # schedule scans every organization. Earlier fixtures may also become due
    # across Shanghai 09:00; scalar_one below verifies this organization's one job.
    assert count >= 1 and schedule(runner, now=now) == 0
    with engine.connect() as c:
        task = c.exec_driver_sql(
            "SELECT task_id FROM collection_jobs WHERE org_id=%s AND plan_id IS NOT NULL", (org,)
        ).scalar_one()
    assert runner.run(org, task) == "succeeded" and len(calls) == 1


def test_console_task_list_detail_retry_and_raw_visibility(engine, setup):
    from app.collection.console import control_task, list_tasks, task_view
    from app.contracts.models import TaskControl

    runner, start, org, _, _, _, _, calls, token = prepared(engine, setup)
    accepted = start()
    tid = task_id(accepted)
    assert runner.run(org, tid) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, token)
        detail = task_view(c, p, tid)
        assert detail["state"] == "succeeded" and detail["outputs"][0]["kind"] == "snapshot"
        assert any(t["id"] == str(tid) for t in list_tasks(c, p, "motion_comic")["items"])
        assert "safe_request" not in detail and "worker_token" not in str(detail)
    with pytest.raises(Denied), engine.begin() as c:
        control_task(
            c,
            authenticate(c, token),
            tid,
            TaskControl(expected_lock_version=detail["lock_version"], reason="retry"),
            runner,
            "retry",
            str(uuid4()),
        )
    assert len(calls) == 1


def test_console_same_evidence_dispatches_knowledge_without_another_paid_call(engine, setup):
    from app.collection.console import create_source, patch_source
    from app.collection.schedule import KnowledgeIntake, schedule
    from app.contracts.models import ConsoleSourceCreate, SourcePatch
    from tests.integration.test_security import grant

    runner, _, org, member, _, _, _, calls, token = prepared(engine, setup)
    runner.handlers[("collection.knowledge-intake", "1")] = KnowledgeIntake()
    with engine.begin() as c:
        grant(c, org, member, member, ["knowledge.edit"])
        p = authenticate(c, token)
        source = create_source(
            c,
            p,
            ConsoleSourceCreate(
                name="both",
                address="uid:stable-author",
                business_code="motion_comic",
                frequency="every_2h",
                purpose="both",
            ),
            str(uuid4()),
        )
        patch_source(
            c,
            p,
            source["id"],
            SourcePatch(expected_lock_version=source["lock_version"], enabled=True),
            str(uuid4()),
        )
        created = c.exec_driver_sql(
            "SELECT created_at FROM collection_plans WHERE id=%s", (source["plan"]["id"],)
        ).scalar_one()
    assert schedule(runner, now=created + timedelta(hours=2)) == 1
    with engine.connect() as c:
        tid = c.exec_driver_sql(
            "SELECT task_id FROM collection_jobs WHERE org_id=%s", (org,)
        ).scalar_one()
    assert runner.run(org, tid) == "succeeded"
    with engine.connect() as c:
        raw = c.exec_driver_sql("SELECT id FROM raw_assets WHERE org_id=%s", (org,)).scalar_one()
        knowledge = c.exec_driver_sql(
            "SELECT id FROM tasks WHERE org_id=%s AND kind='collection.knowledge-intake'", (org,)
        ).scalar_one()
        assert (
            c.exec_driver_sql(
                "SELECT raw_asset_id FROM task_inputs WHERE task_id=%s", (knowledge,)
            ).scalar_one()
            == raw
        )
    assert runner.run(org, knowledge) == "failed"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE id=%s", (knowledge,)
            ).scalar_one()
            == "INSUFFICIENT_MATERIAL"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM knowledge_items WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
    assert len(calls) == 1


def test_console_http_boundaries_and_cancel_replay(engine, setup):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for

    _runner, start, _org, _, _, _, _, calls, token = prepared(engine, setup)
    job = start()
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        with TestClient(app, base_url="http://localhost:8000") as client:
            client.cookies.set("cip_session", token, path="/api/v1")
            headers = {
                "Origin": "http://localhost:5173",
                "X-CSRF-Token": csrf_for(token),
                "Idempotency-Key": str(uuid4()),
            }
            sources = client.get("/api/v1/sources", params={"business_code": "motion_comic"})
            assert sources.status_code == 200, sources.text
            tasks = client.get("/api/v1/tasks", params={"business_code": "motion_comic"})
            assert tasks.status_code == 200, tasks.text
            path = "/api/v1/tasks/" + job["task"]["task_id"] + "/cancel"
            body = {
                "expected_lock_version": job["task"]["lock_version"],
                "reason": "cancel before network",
            }
            assert client.post(path, json=body).status_code == 403
            first = client.post(path, json=body, headers=headers)
            assert first.status_code == 202, first.text
            second = client.post(path, json=body, headers=headers)
            assert second.status_code == 202 and second.json()["data"]["state"] == "cancelled"
    finally:
        app.dependency_overrides.clear()
    assert calls == []


def test_console_remove_creator_archives_source_and_preserves_history(engine, setup):
    from app.collection.console import create_source, list_sources, patch_source
    from app.contracts.models import ConsoleSourceCreate, SourcePatch

    _, _, org, _, _, _, _, calls, token = prepared(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, token)
        source = create_source(
            c,
            p,
            ConsoleSourceCreate(
                name="creator", address="uid:stable-author", business_code="motion_comic"
            ),
            str(uuid4()),
        )
        patched = patch_source(
            c,
            p,
            source["id"],
            SourcePatch(expected_lock_version=source["lock_version"], archived=True),
            str(uuid4()),
        )
        assert patched["archived"] and not patched["enabled"]
        assert all(
            item["id"] != source["id"] for item in list_sources(c, p, "motion_comic")["items"]
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM sources WHERE org_id=%s AND id=%s", (org, source["id"])
            ).scalar_one()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT enabled FROM collection_plans WHERE id=%s", (source["plan"]["id"],)
            ).scalar_one()
            is False
        )
    assert calls == []


def test_console_pagination_cursor_is_scope_bound_and_revocation_invalidates(engine, setup):
    from app.collection.console import list_sources
    from app.collection.paging import page
    from app.collection.service import configure_source

    _, _, org, member, _, _, _, _, token = prepared(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, token)
        configure_source(c, p, "second", "keyword", "漫剧")
        data = list_sources(c, p, "motion_comic")
        first = page(c, p, data, kind="sources", business="motion_comic", limit=1)
        assert first["next_cursor"] and first["total"] == "2"
        second = page(
            c,
            p,
            data,
            kind="sources",
            business="motion_comic",
            limit=1,
            cursor=first["next_cursor"],
        )
        assert second["items"][0]["id"] != first["items"][0]["id"]
    with pytest.raises(Denied, match="CURSOR_EXPIRED"), engine.begin() as c:
        page(
            c, p, data, kind="tasks", business="motion_comic", limit=1, cursor=first["next_cursor"]
        )
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s",
            (org, member),
        )
    with pytest.raises(Denied, match="CURSOR_EXPIRED"), engine.begin() as c:
        page(
            c,
            p,
            data,
            kind="sources",
            business="motion_comic",
            limit=1,
            cursor=first["next_cursor"],
        )


def test_console_paused_or_revoked_plan_never_creates_paid_work(engine, setup):
    from app.collection.console import create_source, patch_source
    from app.collection.schedule import schedule
    from app.contracts.models import ConsoleSourceCreate, SourcePatch

    runner, _, org, member, _, _, _, calls, token = prepared(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, token)
        source = create_source(
            c,
            p,
            ConsoleSourceCreate(
                name="scope", address="漫剧", business_code="motion_comic", frequency="every_2h"
            ),
            str(uuid4()),
        )
        created = c.exec_driver_sql(
            "SELECT created_at FROM collection_plans WHERE id=%s", (source["plan"]["id"],)
        ).scalar_one()
    assert schedule(runner, now=created + timedelta(hours=2)) == 0
    with engine.begin() as c:
        patch_source(
            c,
            authenticate(c, token),
            source["id"],
            SourcePatch(expected_lock_version=source["lock_version"], enabled=True),
            str(uuid4()),
        )
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s",
            (org, member),
        )
    assert schedule(runner, now=created + timedelta(hours=2)) == 0
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT enabled FROM collection_plans WHERE id=%s", (source["plan"]["id"],)
            ).scalar_one()
            is False
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_jobs WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
    assert calls == []


@pytest.mark.parametrize("before_reservation", [False, True])
def test_console_same_connection_plans_wait_without_consuming_attempts(
    engine, setup, before_reservation
):
    from app.collection.console import create_source, patch_source
    from app.collection.schedule import schedule
    from app.contracts.models import ConsoleSourceCreate, SourcePatch

    runner, _, org, _, _, _, _, calls, token = prepared(engine, setup)
    handler = next(iter(runner.handlers.values()))
    handler.min_interval = 60
    with engine.begin() as c:
        p = authenticate(c, token)
        for name in ("first plan", "second plan"):
            source = create_source(
                c,
                p,
                ConsoleSourceCreate(
                    name=name,
                    address="uid:stable-author",
                    business_code="motion_comic",
                    frequency="every_2h",
                ),
                str(uuid4()),
            )
            patch_source(
                c,
                p,
                source["id"],
                SourcePatch(expected_lock_version=source["lock_version"], enabled=True),
                str(uuid4()),
            )
        created = c.exec_driver_sql(
            "SELECT max(created_at) FROM collection_plans WHERE org_id=%s", (org,)
        ).scalar_one()
    assert schedule(runner, now=created + timedelta(hours=2)) == 2
    with engine.connect() as c:
        ids = list(
            c.exec_driver_sql(
                "SELECT task_id FROM collection_jobs WHERE org_id=%s ORDER BY created_at,id", (org,)
            ).scalars()
        )
    if before_reservation:
        ticket = runner.claim(org, ids[0])
        assert ticket is not None and runner.claim(org, ids[1]) is None
        result = handler.execute_ticket(runner, ticket, lambda: runner.heartbeat(ticket))
        assert runner.complete(ticket, result) == "succeeded"
    else:
        assert runner.run(org, ids[0]) == "succeeded"
    assert runner.run(org, ids[1]) == "ignored"
    with engine.connect() as c:
        assert (
            c.exec_driver_sql("SELECT state FROM tasks WHERE id=%s", (ids[1],)).scalar_one()
            == "queued"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_attempts WHERE task_id=%s", (ids[1],)
            ).scalar_one()
            == 0
        )
    handler.min_interval = 0
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE tasks SET available_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
            (ids[1],),
        )
    assert runner.run(org, ids[1]) == "succeeded" and len(calls) == 2


def test_console_cursor_anchor_survives_newer_source_insert(engine, setup):
    from app.collection.console import list_sources
    from app.collection.paging import page
    from app.collection.service import configure_source

    _, _, _, _, _, _, _, _, token = prepared(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, token)
        configure_source(c, p, "second", "keyword", "漫剧")
        first = page(
            c,
            p,
            list_sources(c, p, "motion_comic"),
            kind="sources",
            business="motion_comic",
            limit=1,
        )
    with engine.begin() as c:
        p = authenticate(c, token)
        configure_source(c, p, "newest", "keyword", "漫剧")
        following = page(
            c,
            p,
            list_sources(c, p, "motion_comic"),
            kind="sources",
            business="motion_comic",
            limit=1,
            cursor=first["next_cursor"],
        )
        assert following["items"][0]["id"] != first["items"][0]["id"]


def test_console_business_task_grant_reads_state_without_source_outputs(engine, setup):
    from app.collection.console import task_view
    from tests.integration.test_security import grant

    runner, start, org, member, _, _, _, _, token = prepared(engine, setup)
    job = start()
    assert runner.run(org, task_id(job)) == "succeeded"
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s",
            (org, member),
        )
        grant(c, org, member, member, ["task.read"], "business", "motion_comic")
        state = task_view(c, authenticate(c, token), task_id(job))
        assert state["state"] == "succeeded" and state["outputs"] == []
