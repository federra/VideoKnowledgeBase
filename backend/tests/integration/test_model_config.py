from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.model_config.contracts import BindingsWrite, SourceWrite
from app.model_config.service import resolve, save_bindings, save_source, view
from app.security.errors import Denied
from app.security.sessions import authenticate
from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def source(**patch):
    return SourceWrite(
        **(
            {
                "name": "Source",
                "provider": "deepseek",
                "capability": "text",
                "endpoint": "https://api.deepseek.com",
                "model": "deepseek-chat",
                "secret_ref": "DEEPSEEK_KEY",
                "timeout": 45,
                "retries": 0,
                "max_tokens": 2048,
                "enabled": True,
            }
            | patch
        )
    )


def test_configuration_versions_binding_scope_and_zero_tasks(engine, setup, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_key", SecretStr("test-not-network"))
    with engine.begin() as c:
        grant(c, setup[0], setup[1], setup[1], ["model.configure", "content.write"])
        p = authenticate(c, setup[2])
        assert view(c, p, "motion_comic")["sources"] == []
        key = str(uuid4())
        body = source()
        saved = save_source(c, p, body, key)
        assert save_source(c, p, body, key) == saved
        binding = save_bindings(
            c,
            p,
            BindingsWrite(
                business_code="motion_comic",
                expected_lock_version="0",
                bindings={"topic": saved["id"]},
            ),
            str(uuid4()),
        )
        assert binding["lock_version"] == "1"
        first = resolve(c, p, "motion_comic", "topic")
        assert first["revision_id"]
        second = save_source(
            c, p, source(id=saved["id"], expected_lock_version="1", model="new-model"), str(uuid4())
        )
        assert second["version"] == 2
        assert resolve(c, p, "motion_comic", "topic")["revision_id"] != first["revision_id"]
        assert (
            c.exec_driver_sql(
                "SELECT model_identifier FROM ai_config_revisions WHERE id=%s",
                (first["revision_id"],),
            ).scalar_one()
            == "deepseek-chat"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM tasks WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
        assert "test-not-network" not in str(view(c, p, "motion_comic"))
        with pytest.raises(Denied, match="MODEL_NOT_CONFIGURED"):
            resolve(c, p, "story_short", "topic")
        with pytest.raises(Denied, match="VERSION_CONFLICT"):
            save_source(c, p, source(id=saved["id"], expected_lock_version="1"), str(uuid4()))
        with pytest.raises(Denied, match="VALIDATION_FAILED"):
            save_bindings(
                c,
                p,
                BindingsWrite(
                    business_code="story_short",
                    expected_lock_version="0",
                    bindings={"visual": saved["id"]},
                ),
                str(uuid4()),
            )


def test_console_null_limit_round_trips_to_frozen_config(engine, setup, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_key", SecretStr("test-not-network"))
    with engine.begin() as c:
        grant(c, setup[0], setup[1], setup[1], ["model.configure", "content.write"])
        p = authenticate(c, setup[2])
        saved = save_source(c, p, source(max_tokens=None), str(uuid4()))
        assert saved["max_tokens"] is None
        save_bindings(
            c,
            p,
            BindingsWrite(
                business_code="motion_comic",
                expected_lock_version="0",
                bindings={"topic": saved["id"]},
            ),
            str(uuid4()),
        )
        assert view(c, p, "motion_comic")["sources"][0]["max_tokens"] is None
        assert resolve(c, p, "motion_comic", "topic")["max_tokens"] is None


def test_configuration_requires_permission_before_any_lookup(engine, setup):
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            view(c, p, "motion_comic")


def test_generation_permission_is_not_model_administration(engine, setup, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_key", SecretStr("test-only"))
    with engine.begin() as c:
        grant(
            c,
            setup[0],
            setup[1],
            setup[1],
            ["content.write"],
            scope="business",
            target="motion_comic",
        )
        p = authenticate(c, setup[2])
        with pytest.raises(Denied, match="MODEL_NOT_CONFIGURED"):
            resolve(c, p, "motion_comic", "topic")
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            view(c, p, "motion_comic")
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            resolve(c, p, "story_short", "topic")


def test_http_uses_csrf_and_idempotency_without_exposing_keys(engine, setup, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.model_config.http import mount
    from app.security.http import get_engine
    from app.security.http import mount as mount_auth
    from app.security.sessions import csrf_for

    app = FastAPI()
    mount_auth(app)
    mount(app)
    app.dependency_overrides[get_engine] = lambda: engine
    monkeypatch.setattr(settings, "deepseek_key", SecretStr("never-expose-this"))
    with engine.begin() as c:
        grant(c, setup[0], setup[1], setup[1], ["model.configure"])
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    client.cookies.set("cip_session", setup[2])
    body = source().model_dump(mode="json", exclude_none=True)
    assert client.post("/api/v1/model-config/sources", json=body).status_code == 403
    headers = {
        "Origin": "http://127.0.0.1:5173",
        "X-CSRF-Token": csrf_for(setup[2]),
        "Idempotency-Key": str(uuid4()),
    }
    saved = client.post("/api/v1/model-config/sources", json=body, headers=headers)
    assert saved.status_code == 200, saved.text
    assert "never-expose-this" not in saved.text
    replay = client.post("/api/v1/model-config/sources", json=body, headers=headers)
    assert replay.json()["data"]["id"] == saved.json()["data"]["id"]


def test_modified_connection_cannot_silently_reuse_frozen_secret_reference(
    engine, setup, monkeypatch
):
    monkeypatch.setattr(settings, "deepseek_key", SecretStr("test-only"))
    with engine.begin() as c:
        grant(c, setup[0], setup[1], setup[1], ["model.configure", "content.write"])
        p = authenticate(c, setup[2])
        saved = save_source(c, p, source(), str(uuid4()))
        save_bindings(
            c,
            p,
            BindingsWrite(
                business_code="motion_comic",
                expected_lock_version="0",
                bindings={"topic": saved["id"]},
            ),
            str(uuid4()),
        )
        before = resolve(c, p, "motion_comic", "topic")
        c.exec_driver_sql(
            "UPDATE provider_connections SET secret_ref='OPENAI_API_KEY',lock_version=lock_version+1 WHERE org_id=%s AND id=%s",
            (p.org_id, before["connection_id"]),
        )
        with pytest.raises(Denied, match="MODEL_NOT_CONFIGURED"):
            resolve(c, p, "motion_comic", "topic")


def test_bound_source_cannot_change_to_incompatible_capability(engine, setup):
    with engine.begin() as c:
        grant(c, setup[0], setup[1], setup[1], ["model.configure"])
        p = authenticate(c, setup[2])
        saved = save_source(c, p, source(), str(uuid4()))
        save_bindings(
            c,
            p,
            BindingsWrite(
                business_code="motion_comic",
                expected_lock_version="0",
                bindings={"topic": saved["id"]},
            ),
            str(uuid4()),
        )
        with pytest.raises(Denied, match="VALIDATION_FAILED"):
            save_source(
                c,
                p,
                source(id=saved["id"], expected_lock_version="1", capability="vision"),
                str(uuid4()),
            )
