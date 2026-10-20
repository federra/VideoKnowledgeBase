import json

import httpx
import pytest
from pydantic import SecretStr

from tests.test_feedback_policy import inputs, output


def test_deepseek_single_bounded_json_request_and_evidence_validation():
    from app.ai.deepseek import DeepSeek

    sample = inputs()
    calls = []
    reserved = []

    def transport(request):
        calls.append(request)
        body = json.loads(request.content)
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer offline-fixture"
        assert body["model"] == "deepseek-flash" and body["stream"] is False
        assert body["thinking"] == {"type": "disabled"} and body["max_tokens"] == 2048
        assert body["response_format"] == {"type": "json_object"} and "tools" not in body
        assert "offline-fixture" not in json.dumps(body)
        return httpx.Response(
            200,
            json={
                "id": "fixture-request",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(output(sample))}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    result = DeepSeek(
        lambda: SecretStr("offline-fixture"), transport=httpx.MockTransport(transport)
    ).feedback(sample, reserve=reserved.append)
    assert len(calls) == len(reserved) == 1
    assert (
        result.input_tokens == 100
        and result.output_tokens == 50
        and result.provider_request_id == "fixture-request"
    )
    assert result.validated["classified_count"] == 2


@pytest.mark.parametrize(
    "case",
    ["timeout", "redirect", "empty", "truncated", "foreign_evidence", "oversized", "http401"],
)
def test_deepseek_failures_safe_no_retry(case):
    from app.ai.deepseek import DeepSeek, ModelError

    sample = inputs()
    calls = []

    def transport(request):
        calls.append(request)
        if case == "timeout":
            raise httpx.ReadTimeout("PRIVATE provider body", request=request)
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://evil.invalid"})
        if case == "http401":
            return httpx.Response(401, text="PRIVATE provider body")
        if case == "oversized":
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        value = output(sample)
        if case == "foreign_evidence":
            value["claims"][0]["comment_ids"] = ["00000000-0000-4000-8000-000000000000"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if case == "truncated" else "stop",
                        "message": {"content": "" if case == "empty" else json.dumps(value)},
                    }
                ]
            },
        )

    with pytest.raises(ModelError) as caught:
        DeepSeek(
            lambda: SecretStr("fixture-secret"), transport=httpx.MockTransport(transport)
        ).feedback(sample, reserve=lambda _: None)
    assert "PRIVATE" not in str(caught.value) and "fixture-secret" not in str(caught.value)
    assert len(calls) == 1


def test_no_key_or_reservation_denied_does_not_send():
    from app.ai.deepseek import DeepSeek, ModelError

    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r))
    with pytest.raises(ModelError, match="MODEL_NOT_CONFIGURED"):
        DeepSeek(lambda: None, transport=transport).feedback(inputs(), reserve=lambda _: None)

    def denied(_):
        raise ValueError("BUDGET_EXHAUSTED")

    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        DeepSeek(lambda: SecretStr("test"), transport=transport).feedback(inputs(), reserve=denied)
    assert calls == []


def test_config_supports_user_named_secret_without_echo():
    from app.core.config import Settings

    config = Settings(_env_file=None, deepseek_key="fixture-only")
    assert config.deepseek_key.get_secret_value() == "fixture-only"
    assert "fixture-only" not in repr(config)


def test_invalid_structured_output_preserves_private_raw_output_for_execution_record():
    from app.ai.deepseek import DeepSeek, ModelError

    raw = '{"result_state":"completed","summary":"invalid schema"}'
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "id": "bad-output",
                "choices": [{"finish_reason": "stop", "message": {"content": raw}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
        )
    )
    with pytest.raises(ModelError) as result:
        DeepSeek(lambda: SecretStr("offline"), transport=transport).feedback(
            inputs(), reserve=lambda _: None
        )
    assert result.value.raw_text == raw
    assert "invalid schema" not in str(result.value)


def test_truncated_response_keeps_private_content_usage_and_request_id_without_retry():
    from app.ai.deepseek import DeepSeek, ModelError

    raw = '{"result_state":"completed","summary":"partial'
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "truncated-1",
                "usage": {"prompt_tokens": 100, "completion_tokens": 2048},
                "choices": [{"finish_reason": "length", "message": {"content": raw}}],
            },
        )

    with pytest.raises(ModelError) as caught:
        DeepSeek(lambda: SecretStr("offline"), transport=httpx.MockTransport(transport)).feedback(
            inputs(), reserve=lambda _: None
        )
    assert len(calls) == 1
    assert caught.value.raw_text == raw
    assert caught.value.provider_request_id == "truncated-1"
    assert (caught.value.input_tokens, caught.value.output_tokens) == (100, 2048)
    assert "partial" not in str(caught.value)
