"""Daily-category board contract, offline transport only."""

import json

import httpx
import pytest

CAP = "douyin.board.daily"


def payload():
    return {
        "code": 2000,
        "data": [
            {
                "workId": str(500 + i),
                "workType": "0",
                "category": "小剧场",
                "content": f"真实剧情样本{i}",
                "workUrl": f"https://www.douyin.com/video/{500 + i}",
                "accountName": "剧场作者",
                "accountId": "display-id",
                "duration": 229786,
                "likeCount": i,
                "commentCount": 0,
            }
            for i in range(12)
        ],
    }


def test_daily_board_uses_category_endpoint_and_preserves_order_without_keyword():
    from app.connectors.redfox import RedFox

    calls = []
    request = {"type": "小剧场", "startTime": "2026-10-16", "endTime": "2026-10-16"}

    def transport(r):
        calls.append(r)
        assert r.url.path == "/story/api/dy/search/likesRank"
        assert json.loads(r.content) == request
        return httpx.Response(200, json=payload())

    reply = RedFox(lambda: "offline", transport=httpx.MockTransport(transport)).fetch(
        CAP, request, maximum=10
    )
    assert reply.error is None and len(calls) == 1
    assert reply.batch.view_kind == "board" and reply.batch.returned_items == 12
    assert [r["platform_content_id"] for r in reply.batch.records] == [
        str(500 + i) for i in range(10)
    ]
    first = reply.batch.records[0]
    assert first["content"]["description"] == "真实剧情样本0"
    assert first["content"]["view_count"] is None and first["content"]["duration_ms"] is None
    assert first["platform_uid"] is None


def test_daily_board_does_not_accept_wrong_category_mixed_media_or_hidden_paging():
    from app.connectors.redfox import RedFox, normalize

    body = payload()
    body["data"][0]["category"] = "二次元"
    body["data"][1]["workType"] = "图文"
    batch = normalize(CAP, body, maximum=10)
    assert batch.records[0]["platform_content_id"] == "502"
    connector = RedFox(
        lambda: "offline", transport=httpx.MockTransport(lambda _: pytest.fail("network"))
    )
    for request in [
        {"type": "二次元", "startTime": "2026-10-16", "endTime": "2026-10-16"},
        {"type": "小剧场", "startTime": "2026-10-16", "endTime": "2026-10-17"},
        {"type": "小剧场", "startTime": "2026-10-16", "endTime": "2026-10-16", "page": 1},
    ]:
        with pytest.raises(ValueError):
            connector.fetch(CAP, request, maximum=10)


def test_daily_board_accepts_numeric_zero_alongside_documented_string_video_types():
    from app.connectors.redfox import normalize

    body = payload()
    body["data"][0]["workType"] = 0
    body["data"][1]["workType"] = "视频"
    batch = normalize(CAP, body, maximum=10)
    assert len(batch.records) == 10
    assert batch.records[0]["content"]["source_type_raw"] == "0"
    assert batch.records[1]["content"]["source_type_raw"] == "视频"
