import json

import httpx
import pytest


def test_single_fixed_first_page_request_and_secret_redaction():
    from app.connectors.tikhub import CAPABILITY, TikHub

    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.host == "api.tikhub.io"
        assert request.url.path == "/api/v1/douyin/app/v3/fetch_video_comments"
        assert dict(request.url.params) == {
            "aweme_id": "123456789",
            "cursor": "0",
            "count": "20",
        }
        assert request.headers["Authorization"] == "Bearer offline-secret"
        return httpx.Response(
            200, json={"code": 200, "data": {"unknown_payload": []}, "message": "offline-secret"}
        )

    reply = TikHub(lambda: "offline-secret", transport=httpx.MockTransport(transport)).fetch(
        CAPABILITY, {"aweme_id": "123456789", "cursor": 0, "count": 20}, maximum=20
    )
    assert len(calls) == 1 and reply.outcome == "success" and reply.batch is None
    assert "offline-secret" not in reply.raw_text and json.loads(reply.raw_text)["code"] == 200


@pytest.mark.parametrize(
    "case", ["redirect", "timeout", "provider_error", "invalid_json", "oversize", "missing_data"]
)
def test_failures_are_bounded_safe_and_never_retry(case):
    from app.connectors.tikhub import CAPABILITY, TikHub

    calls = []

    def transport(request):
        calls.append(request)
        if case == "timeout":
            raise httpx.ReadTimeout("PRIVATE " + str(request.url), request=request)
        if case == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.invalid"})
        if case == "provider_error":
            assert request.headers["Authorization"] == "Bearer offline-secret"
        return httpx.Response(200, json={"code": 601, "data": None, "message": "PRIVATE"})
        if case == "invalid_json":
            return httpx.Response(200, text="not json")
        if case == "oversize":
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        return httpx.Response(200, json={"code": 200})

    reply = TikHub(lambda: "offline-secret", transport=httpx.MockTransport(transport)).fetch(
        CAPABILITY, {"aweme_id": "123", "cursor": 0, "count": 20}, maximum=20
    )
    assert len(calls) == 1 and reply.error
    assert "PRIVATE" not in (reply.error or "") and "offline-secret" not in reply.raw_text


def test_no_key_wrong_target_or_extra_page_does_not_call():
    from app.connectors.redfox import AdapterError
    from app.connectors.tikhub import CAPABILITY, TikHub

    calls = []
    connector = TikHub(lambda: None, transport=httpx.MockTransport(lambda r: calls.append(r)))
    with pytest.raises(AdapterError):
        connector.ready()
    for req in [
        {"aweme_id": "123", "cursor": 20, "count": 20},
        {"aweme_id": "https://evil.invalid", "cursor": 0, "count": 20},
        {"aweme_id": "123", "cursor": 0, "count": 20, "token": "other"},
    ]:
        with pytest.raises(AdapterError):
            connector.fetch(CAPABILITY, req, maximum=20)
    assert calls == []


def test_httpx_info_log_never_exposes_header_token(caplog):
    import logging

    from app.connectors.tikhub import CAPABILITY, TikHub

    caplog.set_level(logging.INFO, logger="httpx")
    connector = TikHub(
        lambda: "secret-do-not-log",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"code": 200, "data": None})
        ),
    )
    assert (
        connector.fetch(CAPABILITY, {"aweme_id": "123", "cursor": 0, "count": 20}, maximum=20).error
        is None
    )
    assert caplog.records and "secret-do-not-log" not in caplog.text
