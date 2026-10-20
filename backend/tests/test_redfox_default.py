"""New default search capability; synthetic transport, no paid calls."""

import json

import httpx
import pytest

CAP = "douyin.keyword.default"


def payload():
    return {
        "code": 2000,
        "data": {
            "list": [
                {
                    "workId": str(100 + i),
                    "title": f"漫剧{i}",
                    "content": f"漫剧正片{i}",
                    "workType": "视频",
                    "workUrl": f"https://www.douyin.com/video/{100 + i}",
                    "accountName": "作者",
                    "authorId": "display-name-not-uid",
                    "duration": 60,
                    "likeCount": i,
                    "commentCount": None,
                }
                for i in range(12)
            ]
        },
    }


def test_default_search_uses_exact_relevance_request_preserves_provider_order_and_units():
    from app.connectors.redfox import RedFox

    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.path == "/story/api/dyData/searchArticle"
        assert json.loads(request.content) == {"keyword": "漫剧", "offset": 0, "sortType": "_0"}
        return httpx.Response(200, json=payload())

    result = RedFox(lambda: "offline", transport=httpx.MockTransport(transport)).fetch(
        CAP, {"keyword": "漫剧", "offset": 0, "sortType": "_0"}, maximum=10
    )
    assert len(calls) == 1 and result.error is None
    assert [x["platform_content_id"] for x in result.batch.records] == [
        str(100 + i) for i in range(10)
    ]
    assert result.batch.records[0]["platform_uid"] is None
    assert result.batch.records[0]["account_display_name"] == "作者"
    assert result.batch.records[0]["content"]["view_count"] is None
    assert result.batch.records[0]["content"]["duration_ms"] == 60000


def test_default_search_filters_author_only_and_nonvideo_without_changing_relative_order():
    from app.connectors.redfox import normalize

    body = payload()
    body["data"]["list"][0]["content"] = "其他作品"
    body["data"]["list"][0]["title"] = "其他作品"
    body["data"]["list"][0]["accountName"] = "漫剧作者"
    body["data"]["list"][1]["workType"] = "图文"
    result = normalize(CAP, body, maximum=10)
    assert [x["platform_content_id"] for x in result.records] == [
        str(100 + i) for i in range(2, 12)
    ]


def test_default_search_never_accepts_hot_sort_or_second_page():
    from app.connectors.redfox import RedFox

    calls = []
    connector = RedFox(lambda: "offline", transport=httpx.MockTransport(lambda r: calls.append(r)))
    for change in [{"sortType": "_4"}, {"offset": 20}, {"keyword": "其他"}]:
        with pytest.raises(ValueError):
            connector.fetch(
                CAP, {"keyword": "漫剧", "offset": 0, "sortType": "_0", **change}, maximum=10
            )
    assert calls == []


def test_default_search_keeps_original_body_and_rejects_title_only_keyword():
    from app.connectors.redfox import normalize

    body = payload()
    body["data"]["list"][0]["title"] = "漫剧标题"
    body["data"]["list"][0]["content"] = "普通原文保留"
    body["data"]["list"][1]["title"] = "漫剧"
    original = "漫剧正文完整\n第二行"
    body["data"]["list"][1]["content"] = original
    result = normalize(CAP, body, maximum=10)
    assert result.records[0]["platform_content_id"] == "101"
    assert result.records[0]["content"]["description"] == original
