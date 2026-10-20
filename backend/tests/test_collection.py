"""Provider adapter invariants; synthetic responses are never treated as live RedFox calls."""

import json

import httpx
import pytest


def work(**overrides):
    return {
        "videoId": "9007199254740993123",
        "authorUid": "account-1",
        "authorName": "creator",
        "content": "source description, not transcript",
        "opusUrl": "https://www.douyin.com/video/123",
        "duration": 1234,
        "likeCount": 0,
        "commentCount": None,
        "authorFansCount": "123",
        "publishTime": "2026-10-16 12:30:00",
        "imageUrlList": [],
        "tagList": [],
        **overrides,
    }


def test_broad_normalization_preserves_ids_zero_missing_time_units_and_evidence():
    from app.connectors.redfox import normalize

    batch = normalize(
        "douyin.creator.works",
        {"code": 2000, "data": {"list": [work()]}},
        maximum=1,
        target="account-1",
    )
    row = batch.records[0]
    assert row["platform_content_id"] == "9007199254740993123"
    assert row["content"]["like_count"] == 0 and row["content"]["comment_count"] is None
    assert row["content"]["view_count"] is None and row["content"]["duration_ms"] == 1234
    assert row["content"]["published_at"] is None and row["content"]["publish_timezone"] is None
    assert row["content"]["published_at_raw"] == "2026-10-16 12:30:00"
    assert batch.view_kind == "creator_works" and batch.returned_items == 1


def test_search_accounts_are_not_work_rank_or_work_interactions():
    from app.connectors.redfox import normalize

    batch = normalize(
        "douyin.account.search",
        {
            "code": 2000,
            "data": {
                "list": [
                    {
                        "uid": "a",
                        "nickname": "name",
                        "followerCount": 0,
                        "awemeCount": None,
                        "totalFavorited": 22,
                    }
                ],
                "hasMore": 1,
            },
        },
        maximum=1,
    )
    assert batch.view_kind == "account_discovery"
    assert batch.records[0]["account"]["follower_count"] == 0
    assert batch.records[0]["account"]["work_count"] is None
    assert "content" not in batch.records[0]


def test_duplicate_page_rows_collapse_but_conflicts_do_not_silently_win():
    from app.connectors.redfox import AdapterError, normalize

    batch = normalize(
        "douyin.creator.works", {"code": 2000, "data": {"list": [work(), work()]}}, maximum=3
    )
    assert len(batch.records) == 1 and batch.returned_items == 2
    with pytest.raises(AdapterError, match="INVALID_RESPONSE"):
        normalize(
            "douyin.creator.works",
            {"code": 2000, "data": {"list": [work(), work(likeCount=2)]}},
            maximum=3,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"videoId": None},
        {"videoId": 123},
        {"likeCount": True},
        {"likeCount": -1},
        {"duration": 1.1},
        {"authorFansCount": "1.2万"},
        {"likeCount": 9223372036854775808},
    ],
)
def test_invalid_required_identity_or_counts_reject_whole_page(overrides):
    from app.connectors.redfox import AdapterError, normalize

    with pytest.raises(AdapterError, match="INVALID_RESPONSE"):
        normalize(
            "douyin.creator.works", {"code": 2000, "data": {"list": [work(**overrides)]}}, maximum=1
        )


def test_optional_links_and_alias_placeholders_do_not_become_assets():
    from app.connectors.redfox import normalize

    row = normalize(
        "douyin.creator.works",
        {
            "code": 2000,
            "data": {
                "list": [
                    work(
                        opusUrl="javascript:alert(1)",
                        coverUrl="http://127.0.0.1/a",
                        authorShortId="0",
                    )
                ]
            },
        },
        maximum=1,
    ).records[0]
    assert row["content"]["original_url"] is None and row["content"]["cover_url"] is None
    assert row["aliases"] == []


def test_empty_success_is_different_from_provider_error_and_wrong_author():
    from app.connectors.redfox import AdapterError, normalize

    assert (
        normalize("douyin.creator.works", {"code": 2000, "data": {"list": []}}, maximum=1).records
        == []
    )
    with pytest.raises(AdapterError, match="SOURCE_UNAVAILABLE"):
        normalize("douyin.creator.works", {"code": 3203, "message": "not covered"}, maximum=1)
    with pytest.raises(AdapterError, match="INVALID_RESPONSE"):
        normalize(
            "douyin.creator.works",
            {"code": 2000, "data": {"list": [work()]}},
            maximum=1,
            target="different",
        )


def test_transport_is_fixed_one_call_no_redirect_pagination_or_env_proxy():
    from app.connectors.redfox import RedFox

    requests = []

    def transport(request):
        requests.append(request)
        assert request.headers["REDFOX_API_KEY"] == "dummy-key"
        assert json.loads(request.content) == {"userId": "account-1", "pageNum": 1, "pageSize": 1}
        return httpx.Response(200, json={"code": 2000, "data": {"list": [work()], "total": 100}})

    reply = RedFox(lambda: "dummy-key", transport=httpx.MockTransport(transport)).fetch(
        "douyin.creator.works", {"userId": "account-1", "pageNum": 1, "pageSize": 1}
    )
    assert len(requests) == 1 and reply.http_status == 200 and reply.outcome == "success"
    assert reply.batch.returned_items == 1 and "dummy-key" not in reply.raw_text


@pytest.mark.parametrize(
    "status,code",
    [
        (302, "SOURCE_UNAVAILABLE"),
        (404, "SOURCE_UNAVAILABLE"),
        (410, "SOURCE_UNAVAILABLE"),
        (429, "RATE_LIMITED"),
        (500, "FETCH_FAILED"),
    ],
)
def test_http_failures_do_not_become_empty_success(status, code):
    from app.connectors.redfox import RedFox

    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Location": "https://evil.test/"}, content=b"private vendor failure"
        )

    reply = RedFox(lambda: "dummy-key", transport=httpx.MockTransport(transport)).fetch(
        "douyin.creator.works", {"userId": "account-1", "pageNum": 1, "pageSize": 1}
    )
    assert len(calls) == 1 and reply.error == code and reply.batch is None


def test_network_uncertainty_and_bad_shapes_preserve_safe_failure_and_never_retry():
    from app.connectors.redfox import RedFox

    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("private key", request=request)

    reply = RedFox(lambda: "dummy-key", transport=httpx.MockTransport(timeout)).fetch(
        "douyin.account.search", {"keyword": "漫剧", "offset": 0, "sortType": "_0"}
    )
    assert reply.error == "EXTERNAL_RESULT_UNKNOWN" and reply.http_status is None
    assert len(calls) == 1
    malformed = RedFox(
        lambda: "dummy-key",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="bad dummy-key json")),
    )
    reply = malformed.fetch("douyin.creator.works", {"userId": "a", "pageNum": 1, "pageSize": 1})
    assert reply.error == "INVALID_RESPONSE" and "dummy-key" not in reply.raw_text


def test_provider_response_failure_is_a_serializable_contract_error():
    from typing import get_args

    from app.contracts.models import ERROR_STATUS, ErrorCode

    assert "INVALID_RESPONSE" in get_args(ErrorCode)
    assert ERROR_STATUS["INVALID_RESPONSE"] == 502


def test_missing_key_fails_before_reservation_with_safe_source_code():
    from app.collection.handler import Collect
    from app.connectors.redfox import RedFox
    from app.tasks.service import TaskError

    with pytest.raises(TaskError, match="SOURCE_UNAVAILABLE"):
        Collect(RedFox(lambda: None)).execute_ticket(None, None, lambda: None)
