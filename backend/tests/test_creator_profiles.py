import json

import httpx
import pytest

from app.connectors.creator_profiles import ProfileError, canonical_profile, parse_identity, resolve


def test_profile_canonicalization_rejects_arbitrary_urls_and_deduplicates_tracking():
    assert (
        canonical_profile("https://www.douyin.com/user/MS4wLjAB123?from=share#x")
        == "https://www.douyin.com/user/MS4wLjAB123"
    )
    for url in (
        "http://www.douyin.com/user/123",
        "https://douyin.com.evil/user/123",
        "https://www.douyin.com@127.0.0.1/user/123",
        "https://www.douyin.com/video/123",
        "https://v.douyin.com/abc",
        "https://www.douyin.com:444/user/123",
    ):
        with pytest.raises(ProfileError):
            canonical_profile(url)


def test_identity_requires_same_secuid_never_uses_another_user_or_video_author():
    url = "https://www.douyin.com/user/MS4wLjAB123"

    def html(data):
        return '<script id="RENDER_DATA" type="application/json">' + json.dumps(data) + "</script>"

    assert (
        parse_identity(
            html({"user": {"secUid": "MS4wLjAB123", "uid": "123456", "nickname": "作者"}}), url
        )["uid"]
        == "123456"
    )
    for data in (
        {"user": {"secUid": "other", "uid": "123456"}},
        {"author": {"secUid": "MS4wLjAB123", "uid": "123456"}},
        {"user": {"secUid": "MS4wLjAB123", "uid": "MS4wLjAB123"}},
    ):
        with pytest.raises(ProfileError):
            parse_identity(html(data), url)


def test_resolver_fails_closed_on_redirect_and_does_not_retry():
    calls = []

    def transport(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/"})

    reply = resolve(
        "https://www.douyin.com/user/MS4wLjAB123",
        httpx.Client(transport=httpx.MockTransport(transport)),
    )
    assert reply["status"] == 302 and reply["error"] == "SOURCE_UNAVAILABLE"
    assert len(calls) == 1
