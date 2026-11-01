"""Account lifecycle runs only in an isolated PostgreSQL test database."""

from uuid import uuid4

import pytest

from tests.integration.test_security import engine  # noqa: F401

pytestmark = pytest.mark.database


def test_setup_once_retains_owner_and_account_lifecycle(engine, monkeypatch):  # noqa: F811
    from app.accounts import service
    from app.accounts.contracts import SetupRequest, UserCreate, UserUpdate
    from app.core.config import settings
    from app.core.repository import compare_and_swap
    from app.security.errors import Denied
    from app.security.local import enter
    from app.security.primitives import hash_password
    from app.security.sessions import authenticate, login

    monkeypatch.setattr(settings, "user_accounts_enabled", False)
    with engine.begin() as c:
        _, existing = enter(c)
        org, owner = existing["org_id"], existing["member_id"]
        row = service.member_row(c, org, owner)
        compare_and_swap(
            c,
            "members",
            org,
            owner,
            row["lock_version"],
            {"password_hash": hash_password("original owner password")},
        )
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "user_accounts_enabled", True)

    from app.main import app
    from app.security.http import get_engine

    old_raw, _ = login(engine, org, "__local_owner__", "original owner password", "old-local")
    monkeypatch.setitem(app.dependency_overrides, get_engine, lambda: engine)
    old_client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    old_client.cookies.set("cip_session", old_raw)
    assert old_client.get("/api/v1/session").status_code == 401
    assert (
        old_client.post(
            "/api/v1/access/register",
            json={"email": "pending@example.net", "password": "fixture8"},
            headers={"Origin": "http://127.0.0.1:5173"},
        ).status_code
        == 401
    )
    assert old_client.get("/api/v1/access").json()["data"]["setup_required"] is True
    with engine.begin() as c:
        assert service.access(c)["setup_required"] is True
    from concurrent.futures import ThreadPoolExecutor

    def attempt_setup():
        try:
            with engine.begin() as c:
                return service.setup(
                    c,
                    SetupRequest(
                        login_name="first@example.test",
                        display_name="First",
                        password="new administrator password",
                    ),
                )
        except Denied:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt_setup(), range(2)))
    successful = [result for result in outcomes if result is not None]
    assert len(successful) == 1
    raw, payload = successful[0]
    assert payload["member_id"] == owner
    assert payload["user_accounts_enabled"] is True
    with engine.begin() as c, pytest.raises(Denied):
        service.setup(
            c,
            SetupRequest(
                login_name="takeover", display_name="X", password="takeover password value"
            ),
        )
    with pytest.raises(Denied):
        login(engine, org, "unknown", "unknown account password", "unknown-test")
    with engine.begin() as c:
        p = authenticate(c, raw)
        user = service.create(
            c,
            p,
            uuid4(),
            UserCreate(
                login_name="second@example.test",
                display_name="Second",
                password="regular account password",
                role="user",
            ),
        )
        assert user["role"] == "user"
        user = service.update(
            c,
            p,
            uuid4(),
            user["id"],
            UserUpdate(expected_version=user["lock_version"], display_name="Renamed"),
        )
        assert user["display_name"] == "Renamed"
    regular_raw, _ = login(
        engine, org, "second@example.test", "regular account password", "second-test"
    )
    with engine.begin() as c:
        p = authenticate(c, raw)
        user = service.update(
            c,
            p,
            uuid4(),
            user["id"],
            UserUpdate(
                expected_version=user["lock_version"], password="replacement account password"
            ),
        )
    with engine.begin() as c, pytest.raises(Denied):
        authenticate(c, regular_raw)
    with engine.begin() as c:
        p = authenticate(c, raw)
        original = service.user_view(c, p, owner)
        with pytest.raises(Denied):
            service.update(
                c,
                p,
                uuid4(),
                owner,
                UserUpdate(expected_version=original["lock_version"], enabled=False),
            )
        with pytest.raises(Denied):
            service.update(
                c,
                p,
                uuid4(),
                owner,
                UserUpdate(expected_version=original["lock_version"], role="user"),
            )
    with engine.begin() as c:
        p = authenticate(c, raw)
        user = service.update(
            c,
            p,
            uuid4(),
            user["id"],
            UserUpdate(expected_version=user["lock_version"], role="administrator"),
        )
        assert user["role"] == "administrator"
        user = service.update(
            c,
            p,
            uuid4(),
            user["id"],
            UserUpdate(expected_version=user["lock_version"], enabled=False),
        )
        assert user["enabled"] is False
    with pytest.raises(Denied):
        login(engine, org, "second@example.test", "replacement account password", "disabled-test")


def test_http_accounts_login_csrf_console_and_secret_receipts(engine, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app
    from app.security.http import get_engine

    monkeypatch.setattr(settings, "user_accounts_enabled", True)
    monkeypatch.setattr(settings, "local_single_user", True)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
        access = client.get("/api/v1/access").json()["data"]
        org = access["org_id"]
        assert access["enabled"] and not access["setup_required"]
        assert client.get("/api/v1/session").status_code == 401
        credentials = {
            "org_id": org,
            "login_name": "first@example.test",
            "password": "new administrator password",
        }
        assert client.post("/api/v1/session", json=credentials).status_code == 403
        r = client.post(
            "/api/v1/session", json=credentials, headers={"Origin": "http://127.0.0.1:5173"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["user_accounts_enabled"] is True
        assert "HttpOnly" in r.headers["set-cookie"]
        token = r.json()["data"]["csrf_token"]
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": token,
            "Idempotency-Key": str(uuid4()),
        }
        new = {
            "login_name": "http.user@example.test",
            "display_name": "HTTP user",
            "password": "http account password",
            "role": "user",
        }
        assert (
            client.post(
                "/api/v1/users", json={**new, "login_name": "writer"}, headers=headers
            ).status_code
            == 422
        )
        new["login_name"] = " HTTP.User@Example.TEST "
        r = client.post("/api/v1/users", json=new, headers=headers)
        assert r.status_code == 200, r.text
        uid = r.json()["data"]["id"]
        assert r.json()["data"]["login_name"] == "http.user@example.test"
        longest = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 57 + ".com"
        long_response = client.post(
            "/api/v1/users",
            json={**new, "login_name": longest},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        assert long_response.status_code == 200, long_response.text
        assert long_response.json()["data"]["login_name"] == longest
        assert new["password"] not in r.text
        replay = client.post("/api/v1/users", json=new, headers=headers)
        assert replay.json()["data"]["id"] == uid
        assert (
            client.post(
                "/api/v1/access/setup",
                json={
                    "login_name": "other",
                    "display_name": "Other",
                    "password": "other new account password",
                },
                headers={"Origin": "http://127.0.0.1:5173"},
            ).status_code
            == 403
        )
        assert client.delete("/api/v1/session", headers={"X-CSRF-Token": token}).status_code == 200
        r = client.post(
            "/api/v1/session",
            json={
                **credentials,
                "login_name": "http.user@example.test",
                "password": new["password"],
            },
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert r.status_code == 200, r.text
        assert client.get("/api/v1/users").status_code == 403
        assert client.get("/api/v1/sources?business_code=motion_comic").status_code == 403
        assert client.get("/api/v1/model-config").status_code == 403
        with engine.connect() as c:
            stored = (
                c.exec_driver_sql(
                    "SELECT response::text FROM http_receipts WHERE operation=%s", ("createUser",)
                )
                .scalars()
                .all()
            )
            assert all(new["password"] not in item for item in stored)
    finally:
        app.dependency_overrides.pop(get_engine, None)


def test_last_administrator_concurrent_demotion_serializes(engine, monkeypatch):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor

    from app.accounts import service
    from app.accounts.contracts import UserCreate, UserUpdate
    from app.core.config import settings
    from app.security.errors import Denied
    from app.security.sessions import MemberPrincipal

    monkeypatch.setattr(settings, "user_accounts_enabled", True)
    with engine.begin() as c:
        org = service.access(c)["org_id"]
        owner = c.exec_driver_sql(
            "SELECT id FROM members WHERE org_id=%s AND login_name='first@example.test'", (org,)
        ).scalar_one()
        first = MemberPrincipal(org, owner)
        second = service.create(
            c,
            first,
            uuid4(),
            UserCreate(
                login_name="parallel.admin@example.test",
                display_name="Parallel",
                password="parallel administrator password",
                role="administrator",
            ),
        )
        original = service.user_view(c, first, owner)

    def demote(item):
        ident, version = item
        try:
            with engine.begin() as c:
                service.update(
                    c,
                    MemberPrincipal(org, ident),
                    uuid4(),
                    ident,
                    UserUpdate(expected_version=version, role="user"),
                )
            return "changed"
        except Denied:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                demote, [(owner, original["lock_version"]), (second["id"], second["lock_version"])]
            )
        )
    assert sorted(results) == ["changed", "denied"]
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM members m WHERE m.org_id=%s AND m.disabled_at IS NULL AND EXISTS(SELECT 1 FROM grants g JOIN role_actions a ON a.org_id=g.org_id AND a.role_id=g.role_id WHERE g.org_id=m.org_id AND g.member_id=m.id AND g.scope_kind='org' AND g.revoked_at IS NULL AND a.action_code='member.manage')",
                (org,),
            ).scalar_one()
            == 1
        )


def test_public_registration_fixed_role_normalization_duplicates_and_limit(engine, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app
    from app.security.http import get_engine

    monkeypatch.setattr(settings, "user_accounts_enabled", True)
    monkeypatch.setattr(settings, "local_single_user", True)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50001))
        body = {"email": " Reader.Example@Example.NET ", "password": "fixture8"}
        headers = {"Origin": "http://127.0.0.1:5173"}
        assert client.post("/api/v1/access/register", json=body).status_code == 403
        assert (
            client.post(
                "/api/v1/access/register", json={**body, "role": "administrator"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/access/register", json={**body, "org_id": str(uuid4())}, headers=headers
            ).status_code
            == 422
        )
        response = client.post("/api/v1/access/register", json=body, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()["data"]
        assert payload["display_name"] == "reader.example"
        assert payload["user_accounts_enabled"] is True
        assert (
            "member.manage" not in payload["actions"]
            and "model.configure" not in payload["actions"]
        )
        assert {"content.write", "research.run", "task.read"} <= set(payload["actions"])
        assert (
            "HttpOnly" in response.headers["set-cookie"] and body["password"] not in response.text
        )
        assert client.get("/api/v1/session").status_code == 200
        assert client.get("/api/v1/tasks").status_code == 403
        assert client.get("/api/v1/users").status_code == 403
        assert client.get("/api/v1/model-config").status_code == 403
        assert client.post("/api/v1/access/register", json=body, headers=headers).status_code == 409
        statuses = [
            client.post("/api/v1/access/register", json=body, headers=headers).status_code
            for _ in range(4)
        ]
        assert statuses == [409, 409, 409, 429]
        login = client.post(
            "/api/v1/session",
            json={
                "org_id": payload["org_id"],
                "login_name": " READER.EXAMPLE@EXAMPLE.NET ",
                "password": "fixture8",
            },
            headers=headers,
        )
        assert login.status_code == 200, login.text
        with engine.connect() as c:
            row = c.exec_driver_sql(
                "SELECT login_name,display_name FROM members WHERE id=%s", (payload["member_id"],)
            ).one()
            assert tuple(row) == ("reader.example@example.net", "reader.example")
        monkeypatch.setattr(settings, "user_accounts_enabled", False)
        assert (
            client.post(
                "/api/v1/access/register",
                json={"email": "blocked@example.net", "password": "fixture8"},
                headers=headers,
            ).status_code
            == 403
        )
    finally:
        app.dependency_overrides.pop(get_engine, None)
