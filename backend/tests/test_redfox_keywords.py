"""Synthetic-only invariants for explicitly authorized ten keyword works."""

import httpx
import pytest


def payload():
    return {
        "code": 2000,
        "data": {
            "list": [
                {
                    "videoId": str(1000 + i),
                    "authorUid": "known-uid",
                    "authorName": "漫剧作者",
                    "content": f"漫剧作品 {i}",
                    "likeCount": 0,
                    "shareCount": None,
                    "opusUrl": f"https://www.iesdouyin.com/share/video/{1000 + i}",
                }
                for i in range(12)
            ]
        },
    }


def test_keyword_works_ten_preserve_missing_metrics_and_are_not_board():
    from app.connectors.redfox import normalize

    batch = normalize("douyin.keyword.works", payload(), maximum=10)
    assert (
        batch.view_kind == "keyword_works"
        and len(batch.records) == 10
        and batch.returned_items == 12
    )
    assert batch.records[0]["platform_uid"] == "known-uid"
    assert batch.records[0]["content"]["like_count"] == 0
    assert batch.records[0]["content"]["share_count"] is None


def test_keyword_works_one_request_no_expansion():
    from app.connectors.redfox import RedFox

    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.path == "/story/api/dy/data/searchWork"
        return httpx.Response(200, json=payload())

    connector = RedFox(lambda: "synthetic", transport=httpx.MockTransport(transport))
    body = {"keyword": "漫剧", "exactMatch": True, "pageNum": 1, "pageSize": 10}
    reply = connector.fetch("douyin.keyword.works", body, maximum=10)
    assert reply.error is None and len(calls) == 1 and len(reply.batch.records) == 10
    with pytest.raises(ValueError):
        connector.fetch("douyin.keyword.works", {**body, "pageNum": 2}, maximum=10)
    assert len(calls) == 1
    with pytest.raises(ValueError):
        connector.fetch(
            "douyin.creator.works", {"userId": "x", "pageNum": 1, "pageSize": 10}, maximum=10
        )
