"""Hongguo protocol, precision and sample bounds; no live provider requests."""

import json

import httpx
import pytest

from app.connectors.hongguo import (
    Hongguo,
    encode_html,
    normalize_board,
    parse_comments,
    response_html,
    split_tags,
)
from app.connectors.redfox import AdapterError


def html(board="hot-drama", title="红果热播榜", count=20):
    cards = "".join(
        f'<article aria-labelledby="rank-title-{i}"><a href="/detail?series_id={i}"><h2 id="rank-title-{i}">作品{i}</h2></a>'
        f'<span class="pc-badge-number-x">{i}</span><p class="pc-metrics-x">8070万热度</p>'
        '<ul aria-label="作品互动数据"><li>评分9.1</li><li>68.5万收藏</li><li>221.2万点赞</li></ul>'
        '<p class="pc-description-x">真实结构测试简介</p><p class="pc-categories-x"><span>脑洞.逆袭.异能</span></p></article>'
        for i in range(1, count + 1)
    )
    return f'<link rel="canonical" href="https://hongguoduanju.com/rank/{board}"><h1>{title}</h1><p>10月21日已更新</p><ol aria-label="{title}">{cards}</ol>'


def player(series="1", count=16):
    page = {
        "series_id": series,
        "isSuccess": True,
        "vid": "2",
        "seriesDetail": {"series_id": series, "series_name": "作品1", "vid_list": ["2", "3"]},
        "episodeSocialInfo": {
            "reviews": {
                "total_count": "9506",
                "reviews": [
                    {
                        "content": f"评论{i}",
                        "user_name": "测试昵称",
                        "create_time": "1792339200",
                        "digg_count": "116",
                    }
                    for i in range(count)
                ],
            }
        },
    }
    return (
        "<script>_ROUTER_DATA = "
        + json.dumps({"loaderData": {"player_(series_id)/page": page}})
        + ';throw Error("never run");</script>'
    )


def test_board_limit_numeric_precision_and_first_two_tags():
    batch = normalize_board(html(count=21), "hot-drama")
    assert len(batch.records) == 20
    row = batch.records[0]
    assert row["heat_value"] == 80700000
    assert row["heat_display"] == "8070万热度"
    assert row["genre_tags"] == ["脑洞"]
    assert row["genre_hierarchy"] == [{"genre": "脑洞", "subgenres": ["逆袭"]}]
    assert row["content"]["view_count"] is None
    assert row["content"]["like_count"] == 2212000
    assert split_tags(["脑洞", "逆袭", "异能"]) == ("脑洞", "逆袭")
    assert split_tags(["脑洞·逆袭·异能"]) == ("脑洞", "逆袭")
    assert split_tags([]) == (None, None)


def test_wrong_board_or_unsafe_identity_is_rejected():
    with pytest.raises(AdapterError):
        normalize_board(html(), "hot-ai-drama")
    with pytest.raises(AdapterError):
        normalize_board(html().replace('/detail?series_id=1"', '/detail?series_id=9"'), "hot-drama")


def test_nul_response_roundtrip_and_tamper_rejected():
    raw = html() + "\x00"
    encoded = encode_html(raw)
    assert "\x00" not in encoded and response_html(encoded) == raw
    assert len(normalize_board(encoded, "hot-drama").records) == 20
    corrupted_attribute = html(count=1).replace("作品互动数据", "作品互动数\x00据")
    assert len(normalize_board(encode_html(corrupted_attribute), "hot-drama").records) == 1
    with pytest.raises(AdapterError):
        normalize_board(encoded.replace("8070万", "9999万"), "hot-drama")


def test_comments_maximum_scope_and_missing_platform_ids():
    result = parse_comments(player(), "1")
    assert len(result["comments"]) == 15
    assert result["total_count_reported"] == 9506
    assert result["page_episode_number"] == 1
    assert result["cross_episode_pool_verified"] is False
    assert result["comments"][0]["platform_comment_id"] is None
    assert result["comments"][0]["like_count"] == 116
    with pytest.raises(AdapterError):
        parse_comments(player("4"), "1")
    assert parse_comments(player(count=0), "1")["comments"] == []


def test_missing_rating_is_unknown_not_a_failed_board():
    record = normalize_board(html(count=1).replace("<li>评分9.1</li>", ""), "hot-drama").records[0]
    assert record["score_display"] is None


def test_transport_no_retry_or_redirect_and_cooldown(tmp_path):
    calls = []

    def respond(req):
        calls.append(str(req.url))
        return httpx.Response(429, text="slow down")

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)
    adapter = Hongguo(client=client, throttle_path=tmp_path / "gate.json")
    reply = adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    assert reply.http_status == 429 and reply.error
    with pytest.raises(AdapterError):
        adapter.ready()
    with pytest.raises(AdapterError):
        adapter.fetch("hongguo.board", {"board": "hot-ai-drama"}, maximum=20)
    assert len(calls) == 1
    with pytest.raises(AdapterError):
        adapter.fetch("hongguo.board", {"board": "https://bad.example"}, maximum=20)


def test_interval_survives_connector_recreation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.connectors import hongguo

    now, waits = [100.0], []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(hongguo, "time", SimpleNamespace(time=lambda: now[0], sleep=sleep))
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html(count=1)))
    )
    path = tmp_path / "gate.json"
    assert (
        Hongguo(client, path).fetch("hongguo.board", {"board": "hot-drama"}, maximum=20).error
        is None
    )
    assert (
        Hongguo(client, path).fetch("hongguo.board", {"board": "hot-drama"}, maximum=20).error
        is None
    )
    assert waits == [0, 10] and json.loads(path.read_text())["last_request"] == 110
