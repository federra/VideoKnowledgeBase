"""Disposable PostgreSQL acceptance for explicit saved Hongguo HTTP evidence."""

import hashlib
from uuid import UUID

import pytest

from tests.integration.test_security import grant
from tests.test_hongguo import html
from tests.test_hongguo_saved import capture

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def prepare(engine, setup):
    from app.collection.service import insert

    org, member, *_ = setup
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            ["source.configure", "collection.run", "content.read", "evidence.read"],
        )
        insert(
            c,
            "provider_connections",
            org,
            name="Hongguo public",
            provider_code="hongguo_public",
            secret_ref="PUBLIC_HONGGUO_NO_SECRET",
            enabled=True,
        )
        return insert(
            c,
            "sources",
            org,
            name="saved Hongguo",
            platform_code="hongguo",
            target_kind="board",
            board_code="hot-drama",
            business_code="motion_comic",
            enabled=True,
            created_by=member,
        )


def test_saved_hongguo_manual_time_idempotency_and_zero_calls(engine, setup):
    from app.collection.hongguo_saved import run_saved, submit_saved
    from app.connectors.hongguo import response_html
    from app.intelligence.service import feed, shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import TaskError

    source = prepare(engine, setup)
    body = html() + "\x00"
    meta = capture(body)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        saved = submit_saved(c, p, source, body, meta, "probe-import")
        assert submit_saved(c, p, source, body, meta, "probe-import") == saved
        different = html(count=1)
        with pytest.raises(TaskError, match="IDEMPOTENCY_CONFLICT"):
            submit_saved(c, p, source, different, capture(different), "probe-import")
    result = run_saved(engine, p, saved["task_id"])
    assert result == {"run_outcome": "succeeded", "task_state": "succeeded"}
    assert run_saved(engine, p, saved["task_id"])["run_outcome"] == "ignored"
    with engine.begin() as c:
        result = feed(
            c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), video_catalog="hongguo"
        )
        assert result["total"] == "20" and len(result["items"]) == 10
        raw = (
            c.exec_driver_sql("SELECT * FROM raw_assets WHERE org_id=%s", (setup[0],))
            .mappings()
            .one()
        )
        assert raw["origin"] == "manual" and raw["submitted_by"] == setup[1]
        assert raw["collection_job_id"] is None and raw["collection_call_id"] is None
        assert raw["captured_at"].isoformat() == meta["captured_at"]
        assert response_html(raw["body_text"]) == body
        assert raw["sha256"] == hashlib.sha256(raw["body_text"].encode()).hexdigest()
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT entry_count FROM intelligence_snapshots WHERE job_id=%s",
                (UUID(saved["job_id"]),),
            ).scalar_one()
            == 20
        )
        assert (
            c.exec_driver_sql(
                "SELECT max_external_calls FROM tasks WHERE id=%s", (UUID(saved["task_id"]),)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql("SELECT enabled FROM sources WHERE id=%s", (source,)).scalar_one()
            is False
        )


def test_saved_hongguo_failed_publish_keeps_source_paused(engine, setup, monkeypatch):
    from app.collection import hongguo_saved
    from app.security.sessions import authenticate
    from app.tasks.service import TaskError

    source = prepare(engine, setup)
    body = html(count=1)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        saved = hongguo_saved.submit_saved(c, p, source, body, capture(body), "failed-publish")

    def fail(*args, **kwargs):
        raise TaskError("INVALID_INPUT")

    monkeypatch.setattr(hongguo_saved, "publish_batch", fail)
    assert hongguo_saved.run_saved(engine, p, saved["task_id"])["task_state"] == "failed"
    with engine.begin() as c:
        assert (
            c.exec_driver_sql("SELECT enabled FROM sources WHERE id=%s", (source,)).scalar_one()
            is False
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )


def test_saved_hongguo_other_manual_raw_cannot_enter_snapshot(engine, setup, monkeypatch):
    from app.collection import hongguo_saved
    from app.collection.service import insert
    from app.connectors.hongguo import encode_html
    from app.security.sessions import authenticate

    source = prepare(engine, setup)
    body = html(count=1)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        meta = capture(body)
        saved = hongguo_saved.submit_saved(c, p, source, body, meta, "bound-raw")
        other_body = encode_html(body + " ", capture=capture(body + " "))
        other = insert(
            c,
            "raw_assets",
            setup[0],
            origin="manual",
            asset_kind="response",
            submitted_by=setup[1],
            body_text=other_body,
            sha256=hashlib.sha256(other_body.encode()).hexdigest(),
            captured_at=meta["captured_at"],
        )
    original = hongguo_saved.publish_batch

    def mixed(c, task, raw, job, batch):
        return original(c, task, {**raw, "id": other}, job, batch)

    monkeypatch.setattr(hongguo_saved, "publish_batch", mixed)
    assert hongguo_saved.run_saved(engine, p, saved["task_id"])["task_state"] == "failed"
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )


def test_saved_hongguo_requires_permissions_and_correct_public_connection(engine, setup):
    from app.collection.hongguo_saved import submit_saved
    from app.collection.service import insert
    from app.security.errors import Denied
    from app.security.sessions import authenticate
    from app.tasks.service import TaskError

    body = html(count=1)
    org, member, token, *_ = setup
    with engine.begin() as c:
        source = insert(
            c,
            "sources",
            org,
            name="denied saved Hongguo",
            platform_code="hongguo",
            target_kind="board",
            board_code="hot-drama",
            business_code="motion_comic",
            enabled=False,
            created_by=member,
        )
        p = authenticate(c, token)
        with pytest.raises(Denied):
            submit_saved(c, p, source, body, capture(body), "denied")
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            ["source.configure", "collection.run", "content.read", "evidence.read"],
        )
        insert(
            c,
            "provider_connections",
            org,
            name="wrong identity",
            provider_code="hongguo_public",
            secret_ref="WRONG",
            enabled=True,
        )
        with pytest.raises(TaskError, match="SOURCE_UNAVAILABLE"):
            submit_saved(c, authenticate(c, token), source, body, capture(body), "bad-connection")
        assert (
            c.exec_driver_sql("SELECT count(*) FROM tasks WHERE org_id=%s", (org,)).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM raw_assets WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
