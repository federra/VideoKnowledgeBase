from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_accounts_mode_is_explicit_and_contract_hides_password():
    from app.accounts.contracts import UserCreate
    from app.core.config import Settings

    assert Settings(_env_file=None).user_accounts_enabled is False
    assert UserCreate.model_json_schema()["properties"]["password"]["writeOnly"] is True


def test_administrator_requires_active_org_member_manage(monkeypatch):
    from app.accounts import policy
    from app.security.errors import Denied

    p = SimpleNamespace(org_id=uuid4(), member_id=uuid4())
    monkeypatch.setattr(
        policy,
        "active_grants",
        lambda c, p: [{"action_code": "member.manage", "scope_kind": "business"}],
    )
    assert policy.is_administrator(None, p) is False
    with pytest.raises(Denied):
        policy.require_administrator(None, p)
    monkeypatch.setattr(
        policy,
        "active_grants",
        lambda c, p: [{"action_code": "member.manage", "scope_kind": "org"}],
    )
    assert policy.is_administrator(None, p) is True


def test_console_route_requires_admin_even_with_other_configuration_grants(monkeypatch):
    from app.accounts import policy, service
    from app.core.config import settings
    from app.security import http
    from app.security.errors import Denied

    class Tx:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    class Engine:
        def begin(self):
            return Tx()

    request = SimpleNamespace(
        state=SimpleNamespace(),
        url=SimpleNamespace(hostname="localhost", scheme="http", path="/api/v1/sources"),
        method="GET",
        cookies={"cip_session": "session"},
        headers={},
        scope={"route": SimpleNamespace(operation_id="listSources")},
    )
    monkeypatch.setattr(settings, "user_accounts_enabled", True)
    monkeypatch.setattr(settings, "local_single_user", True)
    monkeypatch.setattr(http, "authenticate", lambda *a, **k: SimpleNamespace(org_id=uuid4()))
    monkeypatch.setattr(service, "require_installation", lambda *a: None)
    monkeypatch.setattr(
        policy,
        "active_grants",
        lambda *a: [{"action_code": "source.configure", "scope_kind": "org"}],
    )
    with pytest.raises(Denied, match="ACCESS_DENIED"):
        http.preflight(request, Engine())


def test_email_registration_normalizes_and_accepts_new_password_policy():
    from pydantic import ValidationError

    from app.accounts.contracts import RegisterRequest, SetupRequest
    from app.security.primitives import hash_password, verify_password

    form = RegisterRequest(email="  Reader.Example@Example.COM  ", password="fixture8")
    assert form.email == "reader.example@example.com"
    assert verify_password("fixture8", hash_password(form.password))
    assert (
        SetupRequest(
            login_name="admin@example.com", display_name="Admin", password="fixture8"
        ).password
        == "fixture8"
    )
    for email in ("missing-at", "a@localhost", "a b@example.com", "a@@example.com"):
        with pytest.raises(ValidationError):
            RegisterRequest(email=email, password="fixture8")
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@example.com", password="fixture8", role="administrator")
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@example.com", password="fixture8", org_id=str(uuid4()))


def test_task_list_is_administrator_only_but_own_status_route_remains_available(monkeypatch):
    from app.accounts import policy, service
    from app.core.config import settings
    from app.security import http
    from app.security.errors import Denied

    class Tx:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    class Engine:
        def begin(self):
            return Tx()

    request = SimpleNamespace(
        state=SimpleNamespace(),
        url=SimpleNamespace(hostname="localhost", scheme="http", path="/api/v1/tasks"),
        method="GET",
        cookies={"cip_session": "session"},
        headers={},
        scope={"route": SimpleNamespace(operation_id="listTasks")},
    )
    monkeypatch.setattr(settings, "user_accounts_enabled", True)
    monkeypatch.setattr(http, "authenticate", lambda *a, **k: SimpleNamespace(org_id=uuid4()))
    monkeypatch.setattr(service, "require_installation", lambda *a: None)
    monkeypatch.setattr(
        policy, "active_grants", lambda *a: [{"action_code": "task.read", "scope_kind": "org"}]
    )
    with pytest.raises(Denied):
        http.preflight(request, Engine())
    request.scope["route"].operation_id = "getTask"
    assert isinstance(http.preflight(request, Engine()), Engine)


def test_admin_created_accounts_require_the_same_normalized_email_as_registration():
    from pydantic import ValidationError

    from app.accounts.contracts import RegisterRequest, UserCreate

    shared = {"password": "fixture8", "display_name": "Reader", "role": "user"}
    for invalid in ("writer", "missing@localhost", "a b@example.com", "a@@example.com"):
        with pytest.raises(ValidationError):
            UserCreate(login_name=invalid, **shared)
    created = UserCreate(login_name=" Writer.Example@Example.COM ", **shared)
    assert created.login_name == "writer.example@example.com"
    longest = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 57 + ".com"
    assert len(longest) == 254
    assert (
        UserCreate(login_name=longest, **shared).login_name
        == RegisterRequest(email=longest, password="fixture8").email
    )
    with pytest.raises(ValidationError):
        UserCreate(login_name="x" + longest, **shared)
