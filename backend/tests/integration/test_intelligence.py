"""S06.3 real PostgreSQL snapshots; synthetic provider transport, no paid calls."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_collection import prepared, task_id

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_feed_exact_day_missing_values_dedup_and_filters(engine, setup):
    from app.intelligence.service import feed
    from app.security.sessions import authenticate

    runner, start, org, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        day = c.exec_driver_sql(
            "SELECT business_date FROM intelligence_snapshots WHERE org_id=%s", (org,)
        ).scalar_one()
        result = feed(c, p, "motion_comic", day, "creator", 1)
        assert result["total"] == "1"
        assert result["items"][0]["entry"]["observation"]["like_count"] == "0"
        assert result["items"][0]["entry"]["observation"]["comment_count"] is None
        assert result["metrics"] == {
            "videos": None,
            "creators": "1",
            "comments": None,
            "likes": "0",
        }
        assert (
            feed(c, p, "motion_comic", day - timedelta(days=1), "creator", 1)["has_snapshot"]
            is False
        )
        assert feed(c, p, "story_short", day, "creator", 1)["items"] == []
        assert feed(c, p, "motion_comic", day, "board", 1)["items"] == []
        assert feed(c, p, "motion_comic", day, "creator", 1, q="absent")["total"] == "0"
        assert feed(c, p, "motion_comic", day, "creator", 1, q="description")["total"] == "1"


def test_feed_latest_version_without_history_overwrite_and_revoke(engine, setup):
    from app.intelligence.service import entries, feed, snapshots
    from app.security.sessions import authenticate

    runner, start, org, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    with engine.begin() as c:
        day = c.exec_driver_sql(
            "SELECT business_date FROM intelligence_snapshots WHERE org_id=%s", (org,)
        ).scalar_one()
        old = snapshots(c, authenticate(c, rest[-1]), "motion_comic", day)[0]
    # Second collection creates another version with the same stable content.
    assert runner.run(org, task_id(start())) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        result = feed(c, p, "motion_comic", day, "creator", 1)
        assert result["total"] == "1"
        assert result["items"][0]["snapshot_version"] == 2
        assert entries(c, p, old["id"], 1, 10)["total"] == "1"
        raw = c.exec_driver_sql(
            "SELECT id FROM raw_assets WHERE org_id=%s ORDER BY created_at DESC LIMIT 1", (org,)
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (gen_random_uuid(),%s,%s,1,'access_revoked','test')",
            (org, raw),
        )
        assert feed(c, p, "motion_comic", day, "creator", 1)["items"] == []
        # Latest inaccessible version must not silently fall back to an old one.
        assert snapshots(c, p, "motion_comic", day) == []


def test_local_entry_no_manual_login_idempotent_and_remote_denied(engine, monkeypatch):
    from app.core.config import settings
    from app.main import app
    from app.security.http import get_engine

    monkeypatch.setattr(settings, "local_single_user", True)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234))
        first = client.get("/api/v1/session")
        assert first.status_code == 200, first.text
        assert first.json()["data"]["display_name"] == "南哥"
        assert "HttpOnly" in first.headers["set-cookie"]
        assert (
            client.get("/api/v1/session").json()["data"]["member_id"]
            == first.json()["data"]["member_id"]
        )
        assert client.get("/api/v1/sources?business_code=motion_comic").status_code == 200
        assert (
            client.get(
                "/api/v1/intelligence/feed?business_code=motion_comic&business_date=2026-10-16"
            ).status_code
            == 200
        )
        assert (
            client.get("/api/v1/session", headers={"Origin": "https://evil.invalid"}).status_code
            == 403
        )
        assert (
            client.get("/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code
            == 403
        )
        remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 1234))
        assert remote.get("/api/v1/session").status_code == 403
        assert client.post("/api/v1/session", json={}).status_code != 200
        with engine.connect() as c:
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM members WHERE login_name='__local_owner__'"
                ).scalar_one()
                == 1
            )
    finally:
        app.dependency_overrides.clear()


def test_feed_http_snapshots_entries_and_cross_tenant_hidden(engine, setup):
    from app.main import app
    from app.security.http import get_engine

    runner, start, org, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        client.cookies.set("cip_session", rest[-1])
        with engine.connect() as c:
            day = c.exec_driver_sql(
                "SELECT business_date FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
        path = f"/api/v1/intelligence/snapshots?business_code=motion_comic&business_date={day}"
        result = client.get(path)
        assert result.status_code == 200, result.text
        snapshot = result.json()["data"][0]
        assert "lock_version" not in snapshot
        result = client.get(f"/api/v1/intelligence/snapshots/{snapshot['id']}/entries")
        assert result.status_code == 200, result.text
        entry = result.json()["data"]["items"][0]
        assert "updated_at" not in entry and "raw_asset_id" not in entry
        result = client.get(
            f"/api/v1/intelligence/feed?business_code=motion_comic&business_date={day}&lane=creator"
        )
        assert result.status_code == 200, result.text
        assert result.json()["data"]["items"][0]["entry"]["id"] == entry["id"]
        assert result.headers["cache-control"] == "no-store"
        assert (
            client.get(
                f"/api/v1/intelligence/feed?business_code=motion_comic&business_date={day}&accounts=bad-id"
            ).status_code
            == 422
        )
        from uuid import uuid4

        assert client.get(f"/api/v1/intelligence/snapshots/{uuid4()}/entries").status_code == 404
        assert (
            client.get(
                f"/api/v1/intelligence/feed?business_code=story_short&business_date={day}"
            ).json()["data"]["items"]
            == []
        )
        # Remove all read grants: counts/options/history must disappear too.
        from app.core.repository import compare_and_swap

        with engine.begin() as c:
            grants = c.exec_driver_sql(
                "SELECT id,lock_version FROM grants WHERE org_id=%s", (org,)
            ).all()
            for gid, version in grants:
                compare_and_swap(
                    c,
                    "grants",
                    org,
                    gid,
                    version,
                    {"revoked_at": c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()},
                )
        assert client.get(path).json()["data"] == []
        assert (
            client.get(f"/api/v1/intelligence/snapshots/{snapshot['id']}/entries").status_code
            == 404
        )
        data = client.get(
            f"/api/v1/intelligence/feed?business_code=motion_comic&business_date={day}&lane=creator"
        ).json()["data"]
        assert (
            data["total"] == "0"
            and data["creators"] == []
            and all(v is None for v in data["metrics"].values())
        )
    finally:
        app.dependency_overrides.clear()


def test_snapshot_author_is_captured_not_mutable_identity(engine, setup):
    from app.intelligence.service import feed
    from app.security.sessions import authenticate

    runner, start, org, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        day = c.exec_driver_sql(
            "SELECT business_date FROM intelligence_snapshots WHERE org_id=%s", (org,)
        ).scalar_one()
        before = feed(c, p, "motion_comic", day, "creator", 1)["items"][0]
        content = c.exec_driver_sql(
            "SELECT id,lock_version FROM external_contents WHERE org_id=%s", (org,)
        ).one()
        from app.collection.service import identity

        other = identity(
            c, "external_accounts", org, "platform_uid", "new-owner", display_name="Changed owner"
        )
        from app.core.repository import compare_and_swap

        compare_and_swap(
            c, "external_contents", org, content.id, content.lock_version, {"account_id": other}
        )
        after = feed(c, p, "motion_comic", day, "creator", 1)["items"][0]
        assert after["account_id"] == before["account_id"]
        assert after["author"] == before["author"]


def test_entry_feedback_missing_is_not_empty_and_exact_day_authorized(engine, setup):
    from uuid import uuid4

    from app.main import app
    from app.security.http import get_engine

    runner, start, org, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    with engine.connect() as c:
        entry, day = c.exec_driver_sql(
            "SELECT e.id,s.business_date FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id WHERE e.org_id=%s",
            (org,),
        ).one()
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        path = f"/api/v1/intelligence/entries/{entry}/feedback?business_code=motion_comic&business_date={day}"
        assert client.get(path).status_code == 401
        client.cookies.set("cip_session", rest[-1])
        result = client.get(path)
        assert result.status_code == 200, result.text
        value = result.json()["data"]
        assert value["status"] == "not_acquired" and value["comments"] == []
        assert value["sample_count"] is None and value["classified_count"] is None
        assert value["feedback_id"] is None and value["claims"] == []
        assert result.headers["cache-control"] == "no-store"
        assert client.get(path.replace("motion_comic", "story_short")).status_code == 404
        assert client.get(path.replace(str(day), str(day - timedelta(days=1)))).status_code == 404
        assert client.get(path.replace(str(entry), str(uuid4()))).status_code == 404
        with engine.begin() as c:
            raw = c.exec_driver_sql(
                "SELECT id FROM raw_assets WHERE org_id=%s", (org,)
            ).scalar_one()
            c.exec_driver_sql(
                "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','test')",
                (org, raw),
            )
        assert client.get(path).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_sealed_feedback_original_evidence_read_and_revocation(engine, setup):
    from uuid import uuid4

    from app.core.repository import claim_task, create_task, finish_task
    from app.intelligence.feedback import entry_feedback, read_feedback
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    runner, start, org, member, source, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    config, provider, file_id, execution, feedback, comment, claim = [uuid4() for _ in range(7)]
    with engine.begin() as c:
        snap, entry, content, day = c.exec_driver_sql(
            "SELECT s.id,e.id,o.content_id,s.business_date FROM intelligence_snapshots s JOIN snapshot_entries e ON e.snapshot_id=s.id JOIN content_observations o ON o.id=e.content_observation_id WHERE s.org_id=%s",
            (org,),
        ).one()
        # Explicit synthetic comment evidence, isolated DB only; separate from the work response.
        from tests.integration.test_schema import raw

        raw_id = raw(c, org, member, "offline fixture original comment")
        c.exec_driver_sql(
            "INSERT INTO provider_connections(id,org_id,provider_code,name,secret_ref) VALUES(%s,%s,'test_fixture','offline','TEST_ONLY')",
            (provider, org),
        )
        c.exec_driver_sql(
            "INSERT INTO ai_config_revisions(id,org_id,config_key,version_no,task_kind,provider_connection_id,model_identifier,output_schema,content_sha256,created_by) VALUES(%s,%s,%s,1,'audience.feedback',%s,'offline-fixture','{}',%s,%s)",
            (config, org, str(config), provider, "b" * 64, member),
        )
        c.exec_driver_sql(
            "INSERT INTO file_objects(id,org_id,storage_backend,storage_key,media_type,byte_size,sha256,validation_state) VALUES(%s,%s,'test',%s,'application/json',2,%s,'accepted')",
            (file_id, org, str(file_id), "c" * 64),
        )
        ident, _ = create_task(
            c,
            {
                "org_id": org,
                "kind": "audience.feedback",
                "handler_version": "1",
                "source_id": source,
                "business_code": "motion_comic",
                "requested_by": member,
                "execution_authorized_by": member,
                "idempotency_key": str(uuid4()),
                "input_sha256": "d" * 64,
                "max_external_calls": 1,
            },
            [
                {"role": "config", "ai_config_revision_id": config},
                {"role": "material", "snapshot_id": snap},
                {"role": "comments", "raw_asset_id": raw_id},
            ],
        )
        attempt, token, version = claim_task(c, org, ident, 2)
        c.exec_driver_sql(
            "INSERT INTO ai_executions(id,org_id,task_id,attempt_id,config_revision_id,invocation_no,input_sha256,input_manifest_file_id) VALUES(%s,%s,%s,%s,%s,1,%s,%s)",
            (execution, org, ident, attempt, config, "d" * 64, file_id),
        )
        c.exec_driver_sql(
            "UPDATE ai_executions SET result_state='completed',output_file_id=%s,finished_at=clock_timestamp() WHERE id=%s",
            (file_id, execution),
        )
        c.exec_driver_sql(
            "INSERT INTO comment_evidence(id,org_id,content_id,raw_asset_id,platform_comment_id,body_text,like_count,captured_at,sample_position) VALUES(%s,%s,%s,%s,'comment-1','期待下一集',0,clock_timestamp(),0)",
            (comment, org, content, raw_id),
        )
        c.exec_driver_sql(
            "INSERT INTO feedback_snapshots(id,org_id,snapshot_id,version_no,task_id,ai_execution_id,sampling_description,sample_count,classified_count,coverage_note) VALUES(%s,%s,%s,1,%s,%s,'offline synthetic fixture',1,1,'不代表整体观众')",
            (feedback, org, snap, ident, execution),
        )
        c.exec_driver_sql(
            "INSERT INTO feedback_comments(org_id,feedback_id,comment_id,position) VALUES(%s,%s,%s,0)",
            (org, feedback, comment),
        )
        c.exec_driver_sql(
            "INSERT INTO feedback_claims(id,org_id,feedback_id,kind,claim_key,text,details,support_count) VALUES(%s,%s,%s,'emotion','expect','期待','{\"trigger\":\"后续发展\"}',1)",
            (claim, org, feedback),
        )
        c.exec_driver_sql(
            "INSERT INTO feedback_claim_evidence(org_id,feedback_id,claim_id,comment_id) VALUES(%s,%s,%s,%s)",
            (org, feedback, claim, comment),
        )
        c.exec_driver_sql("SELECT cip_seal('feedback_snapshots',%s,%s)", (org, feedback))
        finish_task(c, org, ident, attempt, token, version)
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        value = entry_feedback(c, p, entry, "motion_comic", day)
        assert value["status"] == "ready" and value["feedback_id"] == feedback
        assert value["comments"][0]["body_text"] == "期待下一集"
        assert (
            value["comments"][0]["like_count"] == "0" and value["comments"][0]["username"] is None
        )
        assert value["claims"][0]["details"]["trigger"] == "后续发展"
        assert value["classified_count"] == 1
        from app.intelligence.service import feed

        preview = feed(c, p, "motion_comic", day, "creator")["items"][0]
        assert preview["entry"]["feedback_id"] == feedback
        assert preview["feedback_emotions"] == ["期待"]
        assert read_feedback(c, p, feedback)["sample_count"] == 1
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','test')",
            (org, raw_id),
        )
        with pytest.raises(Denied):
            entry_feedback(c, p, entry, "motion_comic", day)
