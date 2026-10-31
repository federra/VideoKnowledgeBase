import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError


def config():
    return {
        "revision_id": str(uuid4()),
        "source_id": str(uuid4()),
        "connection_id": str(uuid4()),
        "provider": "deepseek",
        "model": "deepseek-chat",
        "endpoint": "https://api.deepseek.com",
        "secret_ref": "DEEPSEEK_KEY",
        "timeout": 45,
        "retries": 0,
        "max_tokens": 2048,
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.deepseek.com",
        "https://u:p@example.com",
        "https://127.0.0.1",
        "https://example.com?token=x",
        "https://localhost",
        "https://[::1]",
    ],
)
def test_endpoint_rejects_unsafe_urls(endpoint):
    from app.model_config.transport import validate_endpoint

    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_private_dns_never_reserves_or_sends():
    from app.ai.deepseek import ModelError
    from app.model_config.transport import ConfiguredModel

    calls = []
    model = ConfiguredModel(key=lambda _: SecretStr("secret"), lookup=lambda _: ["10.0.0.1"])
    with pytest.raises(ModelError, match="VALIDATION_FAILED"):
        model.complete(config(), "system", "user", {}, reserve=calls.append)
    assert calls == []


def test_one_call_pinned_public_address_and_reserved_before_send():
    from app.model_config.transport import ConfiguredModel

    reserved = []

    def send(request):
        assert reserved
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == "api.deepseek.com"
        assert request.extensions["sni_hostname"] == "api.deepseek.com"
        assert json.loads(request.content)["model"] == "deepseek-chat"
        assert json.loads(request.content)["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "id": "abc",
                "choices": [{"finish_reason": "stop", "message": {"content": '{"topics":[]}'}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    model = ConfiguredModel(
        key=lambda _: SecretStr("secret"),
        lookup=lambda _: ["8.8.8.8"],
        transport=httpx.MockTransport(send),
    )
    reply = model.complete(config(), "sys", "user", {}, reserve=reserved.append)
    assert reply.validated == {"topics": []}
    assert reply.input_tokens == 3
    assert len(reserved) == 1
    assert "secret" not in json.dumps(reserved)


def test_failure_is_never_automatically_retried():
    from app.ai.deepseek import ModelError
    from app.model_config.transport import ConfiguredModel

    sent = []

    def send(req):
        sent.append(req)
        return httpx.Response(429)

    model = ConfiguredModel(
        key=lambda _: SecretStr("secret"),
        lookup=lambda _: ["8.8.8.8"],
        transport=httpx.MockTransport(send),
    )
    with pytest.raises(ModelError, match="RATE_LIMITED"):
        model.complete(config(), "sys", "user", {}, reserve=lambda _: None)
    assert len(sent) == 1


def test_source_contract_disallows_raw_secret_and_retries():
    from app.model_config.contracts import SourceWrite

    data = {
        "name": "测试",
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
    assert SourceWrite(**data).secret_ref == "DEEPSEEK_KEY"
    for patch in ({"secret_ref": "sk-raw-secret"}, {"retries": 1}, {"name": "   "}):
        with pytest.raises(ValidationError):
            SourceWrite(**(data | patch))


def test_missing_saved_configuration_never_reads_credential():
    from app.ai.deepseek import ModelError
    from app.model_config.transport import ConfiguredModel

    read = []
    with pytest.raises(ModelError, match="MODEL_NOT_CONFIGURED"):
        ConfiguredModel(key=lambda ref: read.append(ref)).complete(
            {}, "sys", "user", {}, reserve=lambda _: None
        )
    assert not read


@pytest.mark.parametrize(
    "status,code",
    [(302, "SOURCE_UNAVAILABLE"), (401, "MODEL_NOT_CONFIGURED"), (500, "SOURCE_UNAVAILABLE")],
)
def test_redirect_and_error_never_follow_or_retry(status, code):
    from app.ai.deepseek import ModelError
    from app.model_config.transport import ConfiguredModel

    requests = []

    def send(req):
        requests.append(req)
        return httpx.Response(status, headers={"location": "https://127.0.0.1"})

    model = ConfiguredModel(
        key=lambda _: SecretStr("secret"),
        lookup=lambda _: ["8.8.8.8"],
        transport=httpx.MockTransport(send),
    )
    with pytest.raises(ModelError, match=code):
        model.complete(config(), "sys", "user", {}, reserve=lambda _: None)
    assert len(requests) == 1


def test_model_heads_have_organization_foreign_keys():
    from app.core.models import metadata

    for name in ("model_sources", "model_bindings"):
        assert any(
            fk.referred_table.name == "organizations"
            for fk in metadata.tables[name].foreign_key_constraints
        )


def test_blank_server_credential_is_not_ready(monkeypatch):
    from app.core.config import settings
    from app.model_config.transport import credential_ready

    monkeypatch.setattr(settings, "deepseek_key", SecretStr("   "))
    assert not credential_ready("DEEPSEEK_KEY")


def test_no_custom_output_limit_is_null_in_console_contract():
    from app.model_config.contracts import SourceWrite

    value = SourceWrite(
        name="供应商控制",
        capability="text",
        **{
            k: v
            for k, v in config().items()
            if k not in ("revision_id", "source_id", "connection_id", "max_tokens")
        },
        max_tokens=None,
    )
    assert value.max_tokens is None


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
def test_null_output_limit_is_omitted_from_provider_request(provider):
    from app.model_config.transport import ConfiguredModel

    captured = []

    def send(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": '{"topics":[]}'}}]},
        )

    reserved = []
    ConfiguredModel(
        key=lambda _: SecretStr("secret"),
        lookup=lambda _: ["8.8.8.8"],
        transport=httpx.MockTransport(send),
    ).complete(
        config() | {"provider": provider, "max_tokens": None}, "s", "u", {}, reserve=reserved.append
    )
    assert "max_tokens" not in captured[0]
    assert "max_tokens" not in reserved[0]["request"]
    assert ("thinking" in captured[0]) == (provider == "deepseek")
