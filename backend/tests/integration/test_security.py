"""S05.2 real database authorization; fixtures are synthetic, never project seeds."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import build_engine
from tests.integration.test_schema import base, execute, material, raw

pytestmark = pytest.mark.database


@pytest.fixture
def engine():
    url = os.environ.get("CIP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Run pnpm db:test for real PostgreSQL acceptance.")
    e = build_engine(url)
    yield e
    e.dispose()


@pytest.fixture
def setup(engine):
    from app.security.governance import bootstrap
    from app.security.sessions import login

    with engine.begin() as c:
        org, member = bootstrap(c, "test org", "admin", "controlled administrator password")
    result = login(engine, org, "admin", "controlled administrator password", "fixture-" + str(org))
    with engine.begin() as c:
        other, _, work = base(c)
    return org, member, result[0], other, work


def grant(c, org, actor, member, actions, scope="org", target=None):
    # Fixture provisioner deliberately bypasses service policy; all real mutation tests
    # use governance. Atomic role+actions+grant under the same org lock.
    role, ident = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO role_definitions(id,org_id,code,name) VALUES (%s,%s,%s,%s)",
        (role, org, str(role), "test role"),
    )
    for action in actions:
        execute(
            c,
            "INSERT INTO role_actions(org_id,role_id,action_code) VALUES (%s,%s,%s)",
            (org, role, action),
        )
    slot = {
        "business": "business_code",
        "work": "work_id",
        "file": "file_id",
        "raw_asset": "raw_asset_id",
        "task": "task_id",
    }.get(scope)
    table = __import__("app.core.models", fromlist=["metadata"]).metadata.tables["grants"]
    c.execute(
        table.insert().values(
            id=ident,
            org_id=org,
            member_id=member,
            role_id=role,
            scope_kind=scope,
            granted_by=actor,
            **({slot: target} if slot else {}),
        )
    )
    return ident


def test_real_login_cookie_csrf_logout_and_no_password_leak(engine, setup):
    from app.main import app
    from app.security.http import get_engine

    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        credentials = {
            "org_id": str(setup[0]),
            "login_name": "admin",
            "password": "controlled administrator password",
        }
        assert client.post("/api/v1/session", json=credentials).status_code == 403
        r = client.post(
            "/api/v1/session", json=credentials, headers={"Origin": "http://127.0.0.1:5173"}
        )
        assert r.status_code == 200, r.text
        assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=lax" in r.headers["set-cookie"]
        assert credentials["password"] not in r.text
        csrf = r.json()["data"]["csrf_token"]
        assert client.get("/api/v1/session").status_code == 200
        assert (
            client.delete("/api/v1/session", headers={"X-CSRF-Token": "x" * 32}).status_code == 403
        )
        assert client.delete("/api/v1/session", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.get("/api/v1/session").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_unknown_wrong_and_disabled_login_are_generic_and_rate_limited(engine, setup):
    from app.security.errors import Denied
    from app.security.sessions import login

    org, member, *_ = setup
    for name in ["missing", "admin"]:
        with pytest.raises(Denied, match="AUTH_INVALID"):
            login(engine, org, name, "incorrect password", "192.0.2.1")
    for _ in range(5):
        try:
            login(engine, org, "locked", "incorrect password", "192.0.2.2")
        except Denied as e:
            assert e.code == "AUTH_INVALID"
    with pytest.raises(Denied, match="RATE_LIMITED"):
        login(engine, org, "locked", "incorrect password", "192.0.2.2")
    with engine.begin() as c:
        execute(
            c,
            "UPDATE members SET disabled_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
            (member,),
        )
    with pytest.raises(Denied, match="AUTH_INVALID"):
        login(engine, org, "admin", "controlled administrator password", "192.0.2.3")


def test_admin_has_no_content_bypass_and_tenant_objects_do_not_leak(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    org, member, token, _other, work = setup
    with engine.begin() as c:
        p = authenticate(c, token)
        az = Authorizer(c, p)
        assert az.list("works") == []
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.read("works", work)
        local = uuid4()
        execute(
            c,
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'secret',%s)",
            (local, org, str(local), member),
        )
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.read("works", local)
        grant(c, org, member, member, ["content.read"], "work", local)
        assert az.read("works", local)["id"] == local
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            az.require("works", local, "content.write")


def test_revoke_filters_list_search_history_and_file_parent_and_stale_principal(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    org, member, token, *_ = setup
    with engine.begin() as c:
        work = uuid4()
        execute(
            c,
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'needle',%s)",
            (work, org, str(work), member),
        )
        _, version = material(c, org, member, work)
        file_id = uuid4()
        execute(
            c,
            "INSERT INTO file_objects(id,org_id,storage_backend,storage_key,media_type,byte_size,sha256,validation_state) VALUES (%s,%s,'local',%s,'text/plain',4,%s,'accepted')",
            (file_id, org, str(file_id), "a" * 64),
        )
        # Actual cover association provides a permitted parent file path.
        execute(
            c,
            "UPDATE works SET cover_file_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (file_id, work),
        )
        gid = grant(
            c, org, member, member, ["content.read", "evidence.read", "file.read"], "work", work
        )
        p = authenticate(c, token)
        az = Authorizer(c, p)
        assert len(az.list("works", q="needle")) == 1
        assert az.read("artifact_versions", version)["id"] == version
        assert az.file(file_id, ("works", work))["id"] == file_id
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.file(file_id)  # A parent-scoped grant never implies standalone file access.
    with engine.begin() as c:
        execute(
            c,
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
            (gid,),
        )
    with engine.begin() as c:
        az = Authorizer(c, p)  # Retained principal is never a cached permission decision.
        assert az.list("works", q="needle") == []
        for kind, ident in [("artifact_versions", version), ("works", work)]:
            with pytest.raises(Denied, match="NOT_FOUND"):
                az.read(kind, ident)
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.file(file_id, ("works", work))


def test_full_source_dependency_withdrawal_hides_history_even_with_work_grant(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    org, member, token, *_ = setup
    with engine.begin() as c:
        work = uuid4()
        execute(
            c,
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'dependent',%s)",
            (work, org, str(work), member),
        )
        # Source references must be added before sealing; build this history explicitly.
        artifact, version, source = uuid4(), uuid4(), raw(c, org, member)
        execute(
            c,
            "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES (%s,%s,%s,%s,'script',%s)",
            (artifact, org, work, str(artifact), member),
        )
        execute(
            c,
            "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,body_text,material_kind,content_sha256,created_by) VALUES (%s,%s,%s,%s,1,'secret summary','script',%s,%s)",
            (version, org, artifact, work, "b" * 64, member),
        )
        execute(
            c,
            "INSERT INTO artifact_version_sources(org_id,artifact_version_id,raw_asset_id,role) VALUES (%s,%s,%s,'primary')",
            (org, version, source),
        )
        execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
        execute(
            c,
            "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (version, artifact),
        )
        grant(c, org, member, member, ["content.read", "evidence.read"], "work", work)
        az = Authorizer(c, authenticate(c, token))
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.read("artifact_versions", version)
        grant(c, org, member, member, ["evidence.read"], "raw_asset", source)
        assert az.read("artifact_versions", version)["body_text"] == "secret summary"
        execute(
            c,
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (%s,%s,%s,1,'access_revoked','test')",
            (uuid4(), org, source),
        )
        assert az.list("artifact_versions", q="secret") == []


def test_idempotent_governance_audit_delegation_and_current_authority_before_replay(engine, setup):
    from app.security.errors import Denied
    from app.security.governance import create_member, delegate, revoke
    from app.security.sessions import authenticate

    org, admin, token, *_ = setup
    key = uuid4()
    with engine.begin() as c:
        p = authenticate(c, token)
        first = create_member(c, p, key, "reader", "reader", "a long reader password")
        assert create_member(c, p, key, "reader", "reader", "a long reader password") == first
        with pytest.raises(Denied, match="IDEMPOTENCY_CONFLICT"):
            create_member(c, p, key, "other", "reader", "a long reader password")
        assert (
            execute(
                c,
                "SELECT count(*) FROM audit_events WHERE org_id=%s AND action_code='member.create'",
                (org,),
            ).scalar_one()
            == 1
        )
        role = execute(
            c, "SELECT id FROM role_definitions WHERE org_id=%s AND code='M'", (org,)
        ).scalar_one()
        gid = delegate(c, p, uuid4(), first, role, "business", "motion_comic")
        revoke(c, p, uuid4(), gid)
        # Self admin grant revoked: replay cannot circumvent current permission.
        own = execute(
            c,
            "SELECT id FROM grants WHERE org_id=%s AND member_id=%s AND revoked_at IS NULL",
            (org, admin),
        ).scalar_one()
        revoke(c, p, uuid4(), own)
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            create_member(c, p, key, "reader", "reader", "a long reader password")


def test_password_change_invalidates_existing_session(engine, setup):
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    org, member, token, *_ = setup
    with engine.begin() as c:
        p = authenticate(c, token)
        execute(
            c,
            "UPDATE members SET password_hash=%s,lock_version=lock_version+1 WHERE id=%s",
            ("changed", member),
        )
    with engine.begin() as c, pytest.raises(Denied, match="AUTH_REQUIRED"):
        authenticate(c, token)
    assert p.org_id == org


def test_visibility_changes_bump_epoch_and_receipts_are_immutable(engine, setup):
    from app.security.governance import create_member
    from app.security.sessions import authenticate

    org, _, token, *_ = setup
    with engine.begin() as c:
        before = execute(
            c, "SELECT authz_version FROM organizations WHERE id=%s", (org,)
        ).scalar_one()
        fid = uuid4()
        execute(
            c,
            "INSERT INTO file_objects(id,org_id,storage_backend,storage_key,media_type,byte_size,sha256) VALUES (%s,%s,'local',%s,'text/plain',1,%s)",
            (fid, org, str(fid), "a" * 64),
        )
        execute(
            c,
            "UPDATE file_objects SET validation_state='accepted',lock_version=lock_version+1 WHERE id=%s",
            (fid,),
        )
        assert (
            execute(c, "SELECT authz_version FROM organizations WHERE id=%s", (org,)).scalar_one()
            > before
        )
        create_member(
            c, authenticate(c, token), uuid4(), "receipt", "receipt", "receipt member password"
        )
    with engine.begin() as c, pytest.raises(Exception, match="immutable"):
        c.execute(text("UPDATE http_receipts SET response='{}' WHERE org_id=:org"), {"org": org})


def test_role_changes_expiry_disable_and_parent_mismatch_apply_without_cache(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.governance import disable_member, set_role_actions
    from app.security.sessions import authenticate

    org, member, token, *_ = setup
    with engine.begin() as c:
        work = uuid4()
        execute(
            c,
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'role',%s)",
            (work, org, str(work), member),
        )
        gid = grant(c, org, member, member, ["content.read"], "work", work)
        p = authenticate(c, token)
        az = Authorizer(c, p)
        assert az.read("works", work)["id"] == work
        role = execute(c, "SELECT role_id FROM grants WHERE id=%s", (gid,)).scalar_one()
        set_role_actions(c, p, uuid4(), role, ["task.read"])
        assert az.list("works") == []
        set_role_actions(c, p, uuid4(), role, ["content.read"])
        assert len(az.list("works")) == 1
        execute(
            c,
            "UPDATE grants SET expires_at=clock_timestamp()+interval '60 milliseconds',lock_version=lock_version+1 WHERE id=%s",
            (gid,),
        )
        execute(c, "SELECT pg_sleep(0.08)")
        assert az.list("works") == []
        version = execute(c, "SELECT lock_version FROM members WHERE id=%s", (member,)).scalar_one()
        disable_member(c, p, uuid4(), member, version)
    with engine.begin() as c, pytest.raises(Denied, match="AUTH_REQUIRED"):
        authenticate(c, token)


def test_concurrent_member_receipt_runs_once_under_tenant_lock(engine, setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.security.governance import create_member
    from app.security.sessions import authenticate

    org, _, token, *_ = setup
    barrier, key = Barrier(2), uuid4()

    def create():
        barrier.wait(timeout=5)
        with engine.begin() as c:
            return create_member(
                c, authenticate(c, token), key, "race", "race", "race member password"
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(create) for _ in range(2)]
        assert results[0].result(timeout=10) == results[1].result(timeout=10)
    with engine.connect() as c:
        assert (
            execute(
                c,
                "SELECT count(*) FROM audit_events WHERE org_id=%s AND action_code='member.create'",
                (org,),
            ).scalar_one()
            == 1
        )


def test_restricted_database_role_can_login_govern_and_authorize(engine):
    import secrets

    from psycopg import sql

    from app.core.database_roles import grant_application
    from app.security.authorization import Authorizer
    from app.security.governance import bootstrap, create_member
    from app.security.sessions import authenticate, csrf_for, login, logout

    role = "cip_s052_role_" + uuid4().hex
    password = secrets.token_urlsafe(32)
    with engine.begin() as c:
        cur = c.connection.driver_connection.cursor()
        cur.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        grant_application(cur, role)
    limited = build_engine(engine.url.set(username=role, password=password))
    try:
        with limited.begin() as c:
            org, member = bootstrap(c, "restricted", "admin", "restricted member password")
        raw_token, _ = login(limited, org, "admin", "restricted member password", "192.0.2.88")
        with limited.begin() as c:
            p = authenticate(c, raw_token)
            assert create_member(c, p, uuid4(), "new", "new", "new member long password")
            assert Authorizer(c, p).list("works") == []
            work, artifact, version, fid = [uuid4() for _ in range(4)]
            source = raw(c, org, member)
            execute(
                c,
                "INSERT INTO file_objects(id,org_id,storage_backend,storage_key,media_type,byte_size,sha256,validation_state) VALUES (%s,%s,'local',%s,'text/plain',1,%s,'accepted')",
                (fid, org, str(fid), "d" * 64),
            )
            execute(
                c,
                "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'restricted nonempty',%s)",
                (work, org, str(work), member),
            )
            execute(
                c,
                "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES (%s,%s,%s,%s,'script',%s)",
                (artifact, org, work, str(artifact), member),
            )
            execute(
                c,
                "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,body_text,material_kind,content_sha256,created_by) VALUES (%s,%s,%s,%s,1,'restricted history','script',%s,%s)",
                (version, org, artifact, work, "d" * 64, member),
            )
            execute(
                c,
                "INSERT INTO artifact_version_sources(org_id,artifact_version_id,raw_asset_id,role) VALUES (%s,%s,%s,'primary')",
                (org, version, source),
            )
            execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
            execute(
                c,
                "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
                (version, artifact),
            )
            execute(
                c,
                "UPDATE works SET cover_file_id=%s,lock_version=lock_version+1 WHERE id=%s",
                (fid, work),
            )
            grant(c, org, member, member, ["content.read", "evidence.read", "file.read"])
            az = Authorizer(c, p)
            assert len(az.list("works", q="restricted nonempty")) == 1
            assert az.read("artifact_versions", version)["body_text"] == "restricted history"
            assert az.file(fid, ("works", work))["id"] == fid
            execute(
                c,
                "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (%s,%s,%s,1,'withdrawn','withdraw')",
                (uuid4(), org, source),
            )
            execute(
                c,
                "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (%s,%s,%s,2,'expired','warning')",
                (uuid4(), org, source),
            )
            assert az.list("artifact_versions") == []
            logout(c, raw_token, csrf_for(raw_token))
        with limited.begin() as c, pytest.raises(Exception, match="permission denied"):
            execute(c, "UPDATE http_receipts SET response='{}'")
    finally:
        limited.dispose()
        with engine.begin() as c:
            cur = c.connection.driver_connection.cursor()
            cur.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_formal_knowledge_search_uses_published_revision_not_candidate(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.sessions import authenticate
    from tests.integration.test_schema import reviewed_knowledge

    org, member, token, *_ = setup
    with engine.begin() as c:
        work = uuid4()
        execute(
            c,
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'knowledge input',%s)",
            (work, org, str(work), member),
        )
        item, revision, request, ai, human = reviewed_knowledge(c, org, member, work)
        pub = uuid4()
        execute(
            c,
            "INSERT INTO knowledge_publications(id,org_id,knowledge_id,revision_id,review_request_id,ai_decision_id,human_decision_id,published_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (pub, org, item, revision, request, ai, human, member),
        )
        execute(
            c,
            "UPDATE knowledge_items SET published_publication_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (pub, item),
        )
        candidate = uuid4()
        execute(
            c,
            "INSERT INTO knowledge_revisions(id,org_id,knowledge_id,version_no,title,body_text,knowledge_type,browse_category,origin,created_by,content_sha256) VALUES (%s,%s,%s,2,'candidate secret','unpublished body','method_rule','genre','manual',%s,%s)",
            (candidate, org, item, member, "f" * 64),
        )
        execute(
            c, "INSERT INTO knowledge_businesses VALUES (%s,%s,'story_short')", (org, candidate)
        )
        execute(c, "SELECT cip_seal('knowledge_revisions',%s,%s)", (org, candidate))
        execute(
            c,
            "UPDATE knowledge_items SET title='candidate secret',current_revision_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (candidate, item),
        )
        grant(c, org, member, member, ["content.read"], "business", "motion_comic")
        az = Authorizer(c, authenticate(c, token))
        read = az.read("knowledge_items", item)
        assert read["current_revision_id"] == revision
        assert "candidate secret" not in str(read)
        assert az.list("knowledge_items", q="candidate secret") == []
        published_title = execute(
            c, "SELECT title FROM knowledge_revisions WHERE id=%s", (revision,)
        ).scalar_one()
        assert len(az.list("knowledge_items", q=published_title)) == 1


def test_file_wrong_parent_task_only_and_expired_session_fail_closed(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.primitives import token as new_token
    from app.security.primitives import token_hash
    from app.security.sessions import authenticate
    from tests.integration.test_schema import task

    org, member, token, *_ = setup
    with engine.begin() as c:
        work = uuid4()
        execute(
            c,
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'task work',%s)",
            (work, org, str(work), member),
        )
        ident = task(c, org, member, work)
        grant(c, org, member, member, ["task.read"], "task", ident)
        az = Authorizer(c, authenticate(c, token))
        assert set(az.read("tasks", ident)) == {"id", "state", "kind", "created_at", "lock_version"}
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.read("works", work)
        fid = uuid4()
        execute(
            c,
            "INSERT INTO file_objects(id,org_id,storage_backend,storage_key,media_type,byte_size,sha256,validation_state) VALUES (%s,%s,'local',%s,'text/plain',1,%s,'accepted')",
            (fid, org, str(fid), "c" * 64),
        )
        grant(c, org, member, member, ["content.read", "file.read"], "work", work)
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.file(fid, ("works", work))
        grant(c, org, member, member, ["file.read"], "file", fid)
        assert az.file(fid)["id"] == fid
        execute(
            c,
            "UPDATE file_objects SET validation_state='rejected',lock_version=lock_version+1 WHERE id=%s",
            (fid,),
        )
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.file(fid)
        expiring = new_token()
        credential = execute(
            c, "SELECT password_hash FROM members WHERE id=%s", (member,)
        ).scalar_one()
        execute(
            c,
            "INSERT INTO auth_sessions(id,org_id,member_id,token_hash,credential_hash,expires_at) VALUES (%s,%s,%s,%s,%s,clock_timestamp()+interval '60 milliseconds')",
            (uuid4(), org, member, token_hash(expiring), token_hash(credential)),
        )
        execute(c, "SELECT pg_sleep(0.08)")
        with pytest.raises(Denied, match="AUTH_REQUIRED"):
            authenticate(c, expiring)


def test_runtime_auth_precedes_csrf_validation_and_logout_is_idempotent(engine, setup):
    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for

    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        assert client.delete("/api/v1/session").status_code == 401
        token = setup[2]
        client.cookies.set("cip_session", token, path="/api/v1")
        for _ in range(2):
            client.cookies.set("cip_session", token, path="/api/v1")
            r = client.delete("/api/v1/session", headers={"X-CSRF-Token": csrf_for(token)})
            assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.clear()


def test_scoped_evidence_permission_uses_actual_carrier(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.sessions import authenticate

    org, member, token, *_ = setup
    with engine.begin() as c:
        source = raw(c, org, member)
        evidence = uuid4()
        execute(
            c,
            "INSERT INTO evidence_refs(id,org_id,raw_asset_id,locator_kind) VALUES (%s,%s,%s,'whole')",
            (evidence, org, source),
        )
        grant(c, org, member, member, ["evidence.read"], "raw_asset", source)
        assert (
            Authorizer(c, authenticate(c, token)).read("evidence_refs", evidence)["id"] == evidence
        )


def test_login_audit_uses_http_request_id_and_nonlocal_http_is_closed(engine, setup):
    from app.main import app
    from app.security.http import get_engine

    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://localhost:8000")
        r = client.post(
            "/api/v1/session",
            headers={"Origin": "http://localhost:5173"},
            json={
                "org_id": str(setup[0]),
                "login_name": "admin",
                "password": "controlled administrator password",
            },
        )
        assert r.status_code == 200
        with engine.connect() as c:
            assert (
                execute(
                    c,
                    "SELECT count(*) FROM audit_events WHERE request_id=%s",
                    (r.headers["X-Request-ID"],),
                ).scalar_one()
                == 1
            )
        remote = TestClient(app, base_url="http://not-local.example")
        remote.cookies.set("cip_session", setup[2], path="/api/v1")
        assert remote.get("/api/v1/session").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_governance_catalog_never_returns_credentials_and_scoped_admin_cannot_escalate(
    engine, setup
):
    from app.security.errors import Denied
    from app.security.governance import catalog, create_member, delegate
    from app.security.sessions import authenticate, login

    org, member, token, *_ = setup
    with engine.begin() as c:
        p = authenticate(c, token)
        roles = catalog(c, p, "roles")
        assert {r["code"] for r in roles} == set("REVAOM")
        assert "password_hash" not in str(catalog(c, p, "members"))
        target = create_member(
            c, p, uuid4(), "business_admin", "business admin", "business administrator password"
        )
        role = next(r["id"] for r in roles if r["code"] == "M")
        delegate(c, p, uuid4(), target, role, "business", "motion_comic")
    other_token, _ = login(
        engine, org, "business_admin", "business administrator password", "192.0.2.99"
    )
    with engine.begin() as c:
        other = authenticate(c, other_token)
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            create_member(c, other, uuid4(), "escalated", "escalated", "escalated member password")
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            delegate(c, other, uuid4(), member, role, "org")
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            delegate(c, other, uuid4(), member, role, "business", "story_short")
        assert delegate(c, other, uuid4(), member, role, "business", "motion_comic")


@pytest.mark.parametrize("event_kind", ["withdrawn", "access_revoked"])
def test_expired_warning_never_restores_revoked_source_or_derived_text(engine, setup, event_kind):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    org, member, token, *_ = setup
    with engine.begin() as c:
        source = raw(c, org, member)
        grant(c, org, member, member, ["evidence.read"], "raw_asset", source)
        az = Authorizer(c, authenticate(c, token))
        execute(
            c,
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (%s,%s,%s,1,%s,'revocation')",
            (uuid4(), org, source, event_kind),
        )
        execute(
            c,
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (%s,%s,%s,2,'expired','warning')",
            (uuid4(), org, source),
        )
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.read("raw_assets", source)
        execute(
            c,
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (%s,%s,%s,3,'availability_restored','explicit restore')",
            (uuid4(), org, source),
        )
        assert az.read("raw_assets", source)["id"] == source


def test_unpublished_knowledge_is_only_readable_through_explicit_candidate_path(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.sessions import authenticate
    from tests.integration.test_schema import knowledge

    org, member, token, *_ = setup
    with engine.begin() as c:
        item, revision = knowledge(c, org, member)
        grant(
            c, org, member, member, ["content.read", "knowledge.candidate.read", "knowledge.edit"]
        )
        az = Authorizer(c, authenticate(c, token))
        for kind, ident in [("knowledge_items", item), ("knowledge_revisions", revision)]:
            with pytest.raises(Denied, match="NOT_FOUND"):
                az.read(kind, ident)
            assert az.candidate(kind, ident)["id"] == ident
        assert az.list("knowledge_items") == []
        assert az.list("knowledge_revisions") == []
        assert len(az.list("knowledge_items", candidate=True)) == 1
        assert len(az.list("knowledge_revisions", candidate=True)) == 1


def test_knowledge_action_scope_is_the_explicit_requested_revision(engine, setup):
    from app.security.authorization import Authorizer
    from app.security.errors import Denied
    from app.security.sessions import authenticate
    from tests.integration.test_schema import reviewed_knowledge

    org, member, token, *_ = setup
    with engine.begin() as c:
        work = uuid4()
        execute(
            c,
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'scope test',%s)",
            (work, org, str(work), member),
        )
        item, revision, request, ai, human = reviewed_knowledge(c, org, member, work)
        pub = uuid4()
        execute(
            c,
            "INSERT INTO knowledge_publications(id,org_id,knowledge_id,revision_id,review_request_id,ai_decision_id,human_decision_id,published_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (pub, org, item, revision, request, ai, human, member),
        )
        execute(
            c,
            "UPDATE knowledge_items SET published_publication_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (pub, item),
        )
        grant(
            c,
            org,
            member,
            member,
            ["content.read", "content.export", "knowledge.edit", "knowledge.candidate.read"],
            "business",
            "motion_comic",
        )
        az = Authorizer(c, authenticate(c, token))
        assert az.require("knowledge_items", item, "content.export")["id"] == item
        assert az.require("knowledge_items", item, "knowledge.edit", candidate=True)["id"] == item
        with pytest.raises(Denied, match="VALIDATION_FAILED"):
            az.require("knowledge_items", item, "knowledge.edit")
        candidate = uuid4()
        execute(
            c,
            "INSERT INTO knowledge_revisions(id,org_id,knowledge_id,version_no,title,body_text,knowledge_type,browse_category,origin,created_by,content_sha256) VALUES (%s,%s,%s,2,'other business candidate','candidate','method_rule','genre','manual',%s,%s)",
            (candidate, org, item, member, "e" * 64),
        )
        execute(
            c, "INSERT INTO knowledge_businesses VALUES (%s,%s,'story_short')", (org, candidate)
        )
        execute(c, "SELECT cip_seal('knowledge_revisions',%s,%s)", (org, candidate))
        execute(
            c,
            "UPDATE knowledge_items SET current_revision_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (candidate, item),
        )
        assert az.require("knowledge_items", item, "content.export")["id"] == item
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.require("knowledge_items", item, "knowledge.edit", candidate=True)
