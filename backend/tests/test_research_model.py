import json

import httpx
import pytest
from pydantic import SecretStr

from tests.test_research_policy import breakdown, sample


def test_research_model_one_json_request_reserved_before_http():
    from app.ai.deepseek import DeepSeek

    events = []

    def transport(request):
        events.append("http")
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash" and body["max_tokens"] == 2048
        assert "tools" not in body and body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "id": "probe",
                "model": "served-model",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(breakdown())}}
                ],
                "usage": {"prompt_tokens": 200, "completion_tokens": 80},
            },
        )

    reply = DeepSeek(
        lambda: SecretStr("fixture"), transport=httpx.MockTransport(transport)
    ).research("decompose", sample(), reserve=lambda manifest: events.append("reserve"))
    assert events == ["reserve", "http"] and reply.validated["anchors"]["c1"]
    assert reply.input_tokens == 200 and reply.output_tokens == 80


@pytest.mark.parametrize("case", ["invalid_evidence", "timeout", "reserve_denied"])
def test_research_transport_no_retry_or_request_before_reservation(case):
    from app.ai.deepseek import DeepSeek, ModelError

    events = []

    def reserve(manifest):
        events.append("reserve")
        if case == "reserve_denied":
            raise RuntimeError("denied")

    def transport(request):
        events.append("http")
        if case == "timeout":
            raise httpx.ReadTimeout("secret", request=request)
        body = breakdown()
        body["claims"][0]["evidence"][0]["quote"] = "invented"
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}]},
        )

    with pytest.raises((ModelError, RuntimeError)):
        DeepSeek(lambda: SecretStr("fixture"), transport=httpx.MockTransport(transport)).research(
            "decompose", sample(), reserve=reserve
        )
    assert events == (["reserve"] if case == "reserve_denied" else ["reserve", "http"])


@pytest.mark.parametrize("outer", [None, [], 7, "text"])
def test_non_object_provider_json_is_closed_as_invalid_response(outer):
    from app.ai.deepseek import DeepSeek, ModelError

    with pytest.raises(ModelError) as error:
        DeepSeek(
            lambda: SecretStr("fixture"),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=json.dumps(outer).encode(),
                    headers={"Content-Type": "application/json"},
                )
            ),
        ).research("decompose", sample(), reserve=lambda m: None)
    assert str(error.value) == "INVALID_RESPONSE"
    assert error.value.raw_text == json.dumps(outer)
