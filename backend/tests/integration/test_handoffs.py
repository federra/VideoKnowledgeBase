"""Frozen evidence packages use synthetic isolated data; no external requests."""

from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.database


def verify_handoff(engine, org, member, session, entry, feedback):
    from app.contracts.models import ResearchEvidenceCreate
    from app.intelligence.handoff import create_handoff, read_handoff
    from app.security.errors import Denied
    from app.security.primitives import digest
    from app.security.sessions import authenticate
    from tests.integration.test_security import grant

    body = ResearchEvidenceCreate(
        business_code="motion_comic",
        business_date=feedback["business_date"],
        snapshot_id=feedback["snapshot_id"],
        snapshot_version=feedback["snapshot_version"],
        feedback_id=feedback["feedback_id"],
        feedback_version=feedback["feedback_version"],
    )
    key = str(uuid4())
    with engine.begin() as c:
        grant(c, org, member, member, ["research.submit"])
    with engine.begin() as c:
        p = authenticate(c, session)
        frozen = create_handoff(c, p, entry, body, key)
        assert create_handoff(c, p, entry, body, key) == frozen
        assert frozen["manifest_sha256"] == digest(frozen["body"])
        assert frozen["body"]["feedback"]["comments"][0]["body_text"] == "期待下一集"
        assert read_handoff(c, p, UUID(frozen["id"])) == frozen
        frozen["body"]["feedback"]["comments"][0]["body_text"] = "client tamper"
        assert (
            read_handoff(c, p, UUID(frozen["id"]))["body"]["feedback"]["comments"][0]["body_text"]
            == "期待下一集"
        )
        with pytest.raises(Denied, match="IDEMPOTENCY_CONFLICT"):
            create_handoff(
                c,
                p,
                entry,
                body.model_copy(update={"feedback_id": None, "feedback_version": None}),
                key,
            )
        with pytest.raises(Denied):
            create_handoff(
                c, p, entry, body.model_copy(update={"business_code": "story_short"}), str(uuid4())
            )
        with pytest.raises(Denied):
            create_handoff(
                c, p, entry, body.model_copy(update={"snapshot_version": 999}), str(uuid4())
            )
        with pytest.raises(Denied):
            create_handoff(
                c, p, entry, body.model_copy(update={"feedback_version": 999}), str(uuid4())
            )
        ident = UUID(frozen["id"])
    # Immutable body cannot be edited by migration owner or restricted application role.
    from sqlalchemy.exc import DBAPIError

    with engine.begin() as c, pytest.raises(DBAPIError), c.begin_nested():
        c.exec_driver_sql(
            "UPDATE intelligence_handoffs SET body='{}'::jsonb WHERE id=%s", (ident,)
        )
    with engine.begin() as c:
        raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM comment_evidence WHERE org_id=%s LIMIT 1", (org,)
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','handoff test')",
            (org, raw),
        )
        p = authenticate(c, session)
        with pytest.raises(Denied):
            read_handoff(c, p, ident)
        with pytest.raises(Denied):
            create_handoff(c, p, entry, body, key)
        # Rollback withdrawal; caller continues its independent insight withdrawal test.
        c.rollback()


pytest_plugins = ("tests.integration.test_security",)


def test_handoff_http_missing_feedback_csrf_current_authority_and_frozen_snapshot(engine, setup):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for
    from tests.integration.test_collection import prepared, task_id
    from tests.integration.test_security import grant

    runner, start, org, member, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    token = rest[-1]
    with engine.connect() as c:
        entry, snap, version, day = c.exec_driver_sql(
            "SELECT e.id,s.id,s.version_no,s.business_date FROM snapshot_entries e JOIN intelligence_snapshots s ON s.org_id=e.org_id AND s.id=e.snapshot_id WHERE e.org_id=%s",
            (org,),
        ).one()
    body = {
        "business_code": "motion_comic",
        "business_date": str(day),
        "snapshot_id": str(snap),
        "snapshot_version": version,
        "feedback_id": None,
        "feedback_version": None,
    }
    headers = {
        "X-CSRF-Token": csrf_for(token),
        "Idempotency-Key": str(uuid4()),
        "Origin": "http://localhost:5173",
    }
    url = f"/api/v1/intelligence/entries/{entry}/research-evidence"
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        with TestClient(app,base_url="http://localhost:8000") as client:
            client.cookies.set("cip_session", token, path="/api/v1")
            assert client.post(url, json=body).status_code == 403
            assert client.post(url, json=body, headers=headers).status_code == 403
            with engine.begin() as c:
                grant(c, org, member, member, ["research.submit"])
            response = client.post(url, json=body, headers=headers)
            assert response.status_code == 201, response.json()
            frozen = response.json()["data"]
            assert frozen["body"]["feedback"]["status"] == "not_acquired"
            assert frozen["body"]["feedback"]["comments"] == []
            assert client.post(url, json=body, headers=headers).json()["data"] == frozen
            assert (
                client.get("/api/v1/intelligence/research-evidence/" + frozen["id"]).json()["data"]
                == frozen
            )
            assert client.post(url, json={**body, "body": {}}, headers=headers).status_code == 422
            assert (
                client.post(
                    url, json={**body, "feedback_id": str(uuid4())}, headers=headers
                ).status_code
                == 422
            )
            assert (
                client.post(
                    url, json={**body, "business_code": "story_short"}, headers=headers
                ).status_code
                == 404
            )
            assert (
                client.get("/api/v1/intelligence/research-evidence/" + str(uuid4())).status_code
                == 404
            )
            # A later collection and current source rename do not rewrite the original package.
            assert runner.run(org, task_id(start())) == "succeeded"
            assert (
                client.get("/api/v1/intelligence/research-evidence/" + frozen["id"]).json()["data"]
                == frozen
            )
            with engine.begin() as c:
                c.exec_driver_sql(
                    "DELETE FROM role_actions WHERE org_id=%s AND action_code='research.submit'",
                    (org,),
                )
            assert client.post(url, json=body, headers=headers).status_code == 403
            # Same package remains readable when only submit permission was withdrawn.
            assert (
                client.get("/api/v1/intelligence/research-evidence/" + frozen["id"]).status_code
                == 200
            )
    finally:
        app.dependency_overrides.clear()
