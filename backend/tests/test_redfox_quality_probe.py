import json

import httpx


def test_quality_probe_is_video_search_fixed_hot_order_and_one_request():
    from scripts.probe_redfox_quality import fetch_once

    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/story/api/dyData/searchArticle"
        assert json.loads(request.content) == {"keyword": "漫剧", "offset": 0, "sortType": "_4"}
        return httpx.Response(
            200,
            json={
                "code": 2000,
                "data": {"list": [{"workId": "1", "content": "漫剧", "likeCount": 123}]},
            },
        )

    raw, summary = fetch_once("offline", transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and summary["returned_items"] == 1
    assert summary["view_metric_fields"] == [] and summary["can_verify_play_count"] is False
    assert json.loads(raw)["code"] == 2000


def test_quality_probe_keeps_failure_evidence_and_never_retries():
    from scripts.probe_redfox_quality import fetch_once

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"code": 3203, "message": "offline-secret"})

    raw, summary = fetch_once("offline-secret", transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and summary["success"] is False
    assert "offline-secret" not in raw
