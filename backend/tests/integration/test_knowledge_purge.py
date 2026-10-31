"""Permanent erasure runs only against disposable acceptance databases."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.repository import VersionConflict
from app.security.errors import Denied
from tests.integration.test_knowledge_recycle import request, samples

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def recycled(engine, setup):
    from app.knowledge.recycle import change, listing

    p, original = samples(engine, setup)
    with engine.begin() as c:
        change(c, p, uuid4(), request(original))
        return p, original, listing(c, p, "motion_comic")["items"]


def erase_request(items):
    from app.knowledge.contracts import KnowledgePurgeWrite

    return KnowledgePurgeWrite(**request(items).model_dump(), confirmation="PERMANENTLY_DELETE")


def test_permanent_purge_erases_payload_and_index_cannot_restore_or_read_replays(engine, setup):
    from app.knowledge.purge import purge
    from app.knowledge.recycle import change, listing
    from app.security.authorization import Authorizer

    p, original, rows = recycled(engine, setup)
    key, body = uuid4(), erase_request(rows)
    with engine.begin() as c:
        result = purge(c, p, key, body)
        assert purge(c, p, key, body) == result
        assert listing(c, p, "motion_comic")["items"] == []
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM knowledge_items WHERE org_id=%s AND purged_at IS NOT NULL",
                (p.org_id,),
            ).scalar_one()
            == 2
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM knowledge_revisions WHERE org_id=%s AND body_text<>'[已永久删除]'",
                (p.org_id,),
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM search_documents WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM audit_events WHERE org_id=%s AND action_code='knowledge.purged'",
                (p.org_id,),
            ).scalar_one()
            == 2
        )
    for item in original:
        with pytest.raises(Denied), engine.begin() as c:
            Authorizer(c, p, include_recycled=True).read("knowledge_revisions", item["revision_id"])
    with pytest.raises(Denied), engine.begin() as c:
        change(c, p, uuid4(), request(rows), restore=True)


def test_purge_batch_stale_or_not_recycled_is_atomic(engine, setup):
    from app.knowledge.purge import purge
    from app.knowledge.recycle import listing

    p, _, rows = recycled(engine, setup)
    wrong = erase_request(rows).model_copy(deep=True)
    wrong.items[1].expected_lock_version = "999"
    with pytest.raises(Exception, match="VERSION_CONFLICT"), engine.begin() as c:
        purge(c, p, uuid4(), wrong)
    with engine.begin() as c:
        assert listing(c, p, "motion_comic")["total"] == "2"
    from app.knowledge.recycle import change

    with engine.begin() as c:
        change(c, p, uuid4(), request(rows[:1]), restore=True)
    with pytest.raises(VersionConflict), engine.begin() as c:
        purge(c, p, uuid4(), erase_request(rows))


def test_retention_only_at_30_days_expired_hidden_and_not_restorable(engine, setup):
    from app.core.repository import compare_and_swap
    from app.knowledge.purge import cleanup_expired
    from app.knowledge.recycle import change, listing

    p, _, rows = recycled(engine, setup)
    now = datetime.now(UTC)
    with engine.begin() as c:
        compare_and_swap(
            c,
            "knowledge_items",
            p.org_id,
            rows[0]["id"],
            int(rows[0]["lock_version"]),
            {"recycled_at": now - timedelta(days=29, hours=23)},
        )
        compare_and_swap(
            c,
            "knowledge_items",
            p.org_id,
            rows[1]["id"],
            int(rows[1]["lock_version"]),
            {"recycled_at": now - timedelta(days=30)},
        )
        assert listing(c, p, "motion_comic")["total"] == "1"
    expired = request(rows[1:])
    expired.items[0].expected_lock_version = str(int(rows[1]["lock_version"]) + 1)
    with pytest.raises(Exception, match="VERSION_CONFLICT"), engine.begin() as c:
        change(c, p, uuid4(), expired, restore=True)
    assert cleanup_expired(engine) == 1
    assert cleanup_expired(engine) == 0
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM knowledge_items WHERE org_id=%s AND purged_at IS NULL",
                (p.org_id,),
            ).scalar_one()
            == 1
        )


def test_purge_contract_requires_explicit_confirmation():
    from pydantic import ValidationError

    from app.knowledge.contracts import KnowledgePurgeWrite

    with pytest.raises(ValidationError):
        KnowledgePurgeWrite(items=[{"id": uuid4(), "expected_lock_version": "1"}])


def test_restricted_db_role_cannot_spoof_purge_context_but_narrow_function_works(engine, setup):
    from psycopg import sql

    from app.core.database_roles import grant_application
    from app.knowledge.purge import purge

    p, _, rows = recycled(engine, setup)
    role = "cip_purge_test_" + uuid4().hex
    with engine.begin() as c:
        cur = c.connection.driver_connection.cursor()
        cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        grant_application(cur, role)
    try:
        with pytest.raises(Exception, match="immutable|protected"), engine.begin() as c:
            c.connection.driver_connection.cursor().execute(
                sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role))
            )
            c.exec_driver_sql(
                "SELECT set_config('cip.purge_knowledge',%s,true),set_config('cip.purge_org',%s,true)",
                (str(rows[0]["id"]), str(p.org_id)),
            )
            c.exec_driver_sql(
                "UPDATE knowledge_items SET purged_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND id=%s",
                (p.org_id, rows[0]["id"]),
            )
        with engine.begin() as c:
            c.connection.driver_connection.cursor().execute(
                sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role))
            )
            assert len(purge(c, p, uuid4(), erase_request(rows))["ids"]) == 2
        with pytest.raises(Exception, match="immutable"), engine.begin() as c:
            c.connection.driver_connection.cursor().execute(
                sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role))
            )
            c.exec_driver_sql(
                "UPDATE knowledge_items SET purged_at=NULL,recycled_at=NULL,recycled_by=NULL,lock_version=lock_version+1 WHERE org_id=%s AND id=%s",
                (p.org_id, rows[0]["id"]),
            )
    finally:
        with engine.begin() as c:
            cur = c.connection.driver_connection.cursor()
            cur.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_purge_http_requires_csrf_confirmation_and_erasure_hides_old_version(engine, setup):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.http import get_engine

    _, original, rows = recycled(engine, setup)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        client.cookies.set("cip_session", setup[2])
        csrf = client.get("/api/v1/session").json()["data"]["csrf_token"]
        body = erase_request(rows).model_dump(mode="json")
        assert client.post("/api/v1/knowledge/purge", json=body).status_code == 403
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": str(uuid4()),
        }
        assert (
            client.post(
                "/api/v1/knowledge/purge",
                json=request(rows).model_dump(mode="json"),
                headers=headers,
            ).status_code
            == 422
        )
        result = client.post("/api/v1/knowledge/purge", json=body, headers=headers)
        assert result.status_code == 200, result.text
        assert (
            client.post("/api/v1/knowledge/purge", json=body, headers=headers).json()["data"]
            == result.json()["data"]
        )
        assert (
            client.get("/api/v1/knowledge/recycle-bin?business_code=motion_comic").json()["data"][
                "total"
            ]
            == "0"
        )
        assert client.get("/api/v1/knowledge/" + str(original[0]["id"])).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_restore_batch_with_one_expired_is_atomic_and_stale_cleanup_skips_restored(engine, setup):
    from app.core.repository import VersionConflict, compare_and_swap
    from app.knowledge.purge import cleanup_expired
    from app.knowledge.recycle import change

    p, _, rows = recycled(engine, setup)
    with engine.begin() as c:
        compare_and_swap(
            c,
            "knowledge_items",
            p.org_id,
            rows[1]["id"],
            int(rows[1]["lock_version"]),
            {"recycled_at": datetime.now(UTC) - timedelta(days=30)},
        )
    body = request(rows)
    body.items[1].expected_lock_version = str(int(rows[1]["lock_version"]) + 1)
    with pytest.raises(VersionConflict), engine.begin() as c:
        change(c, p, uuid4(), body, restore=True)
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM knowledge_items WHERE org_id=%s AND recycled_at IS NOT NULL",
                (p.org_id,),
            ).scalar_one()
            == 2
        )
        change(c, p, uuid4(), request(rows[:1]), restore=True)
        assert (
            c.exec_driver_sql(
                "SELECT cip_purge_knowledge(%s,%s,%s,NULL,true)",
                (p.org_id, rows[0]["id"], int(rows[0]["lock_version"])),
            ).scalar_one()
            is False
        )
    assert cleanup_expired(engine) == 1
    with engine.connect() as c:
        assert c.exec_driver_sql(
            "SELECT purged_at IS NULL AND recycled_at IS NULL FROM knowledge_items WHERE org_id=%s AND id=%s",
            (p.org_id, rows[0]["id"]),
        ).scalar_one()


def test_concurrent_manual_purge_and_restore_cannot_both_succeed(engine, setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.core.repository import VersionConflict
    from app.knowledge.purge import purge
    from app.knowledge.recycle import change

    p, _, rows = recycled(engine, setup)
    ready = Barrier(2)

    def attempt(erasing):
        ready.wait(timeout=5)
        try:
            with engine.begin() as c:
                if erasing:
                    purge(c, p, uuid4(), erase_request(rows[:1]))
                else:
                    change(c, p, uuid4(), request(rows[:1]), restore=True)
            return True
        except (Denied, VersionConflict):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, flag) for flag in (True, False)]
        assert sum(f.result(timeout=10) for f in futures) == 1
    with engine.connect() as c:
        row = (
            c.exec_driver_sql(
                "SELECT recycled_at,purged_at FROM knowledge_items WHERE org_id=%s AND id=%s",
                (p.org_id, rows[0]["id"]),
            )
            .mappings()
            .one()
        )
        assert row["recycled_at"] is None or row["purged_at"] is not None
