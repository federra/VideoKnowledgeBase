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


@pytest.mark.parametrize(
    "case,expected_bytes,stage,kind,complete",
    [
        ("transfer", b"partial-page", "receive", "transfer_error", False),
        ("decode", b"\xff\xfe", "decode", "invalid_utf8", True),
        ("empty", b"", "receive", "empty_body", True),
        ("shape", b"<html>wrong page</html>", "parse", "invalid_shape", True),
        ("limit", b"x" * (4 * 1024 * 1024), "receive", "body_too_large", False),
    ],
    ids=["transfer", "decode", "empty", "shape", "limit"],
)
def test_failed_response_preserves_bounded_bytes_and_safe_failure_stage(
    tmp_path, case, expected_bytes, stage, kind, complete
):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial-page"
            raise httpx.ReadError("secret=value-must-not-leak")

    payload = expected_bytes + b"x" if case == "limit" else expected_bytes

    def respond(req):
        if case == "transfer":
            return httpx.Response(200, stream=Interrupted())
        return httpx.Response(200, content=payload)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    adapter = Hongguo(client, tmp_path / "gate.json")
    reply = adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    assert reply.error == ("SOURCE_UNAVAILABLE" if case == "transfer" else "INVALID_RESPONSE")
    captured = list(tmp_path.glob("board-hot-drama-*.body"))
    assert len(captured) == 1 and captured[0].read_bytes() == expected_bytes
    meta = json.loads(captured[0].with_suffix(".json").read_text())
    assert meta["failure_stage"] == stage and meta["failure_kind"] == kind
    assert meta["body_complete"] is complete
    assert meta["saved_bytes"] == len(expected_bytes)
    assert "value-must-not-leak" not in reply.raw_text + json.dumps(meta)
    if case == "shape":
        # Complete UTF-8 evidence must still satisfy the existing exact-raw recovery gate.
        assert "capture" not in json.loads(reply.raw_text)
        assert response_html(reply.raw_text) == "<html>wrong page</html>"
    else:
        assert json.loads(reply.raw_text)["capture"]["failure_kind"] == kind
    with pytest.raises(AdapterError):
        adapter.ready()
    with pytest.raises(AdapterError):
        adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    assert len(list(tmp_path.glob("*.body"))) == 1


def test_failed_capture_storage_error_does_not_skip_cooldown(tmp_path, monkeypatch):
    from app.connectors import hongguo

    original_open = hongguo.os.open

    def deny_capture(path, *args, **kwargs):
        if str(path).endswith(".body"):
            raise OSError("capture storage unavailable")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(hongguo.os, "open", deny_capture)
    adapter = Hongguo(
        httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(429, text="slow"))),
        tmp_path / "gate.json",
    )
    with pytest.raises(OSError):
        adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    with pytest.raises(AdapterError):
        adapter.ready()


@pytest.mark.parametrize("status", [403, 429])
def test_empty_http_error_keeps_http_failure_and_cooldown(tmp_path, status):
    adapter = Hongguo(
        httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(status, content=b""))
        ),
        tmp_path / "gate.json",
    )
    reply = adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    assert reply.http_status == status
    assert reply.outcome == "http_error" and reply.error == "SOURCE_UNAVAILABLE"
    with pytest.raises(AdapterError):
        adapter.ready()


def test_content_decompression_failure_is_distinguished_from_transfer(tmp_path):
    adapter = Hongguo(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"not gzip")
                )
            )
        ),
        tmp_path / "gate.json",
    )
    reply = adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    capture = json.loads(reply.raw_text)["capture"]
    assert capture["failure_stage"] == "decode"
    assert capture["failure_kind"] == "content_decode_error"
    assert capture["content_encoding"] == "gzip"
    assert capture["body_complete"] is False
    assert capture["exception_type"] == "DecodingError"


def test_requests_identity_body_instead_of_httpx_default_compression(tmp_path):
    requests = []

    def respond(req):
        requests.append(req)
        # The fixed page does not need compression; prefer the directly observable body.
        assert req.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=httpx.ByteStream(html(count=1).encode()))

    adapter = Hongguo(httpx.Client(transport=httpx.MockTransport(respond)), tmp_path / "gate.json")
    reply = adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    assert reply.error is None and len(reply.batch.records) == 1
    assert len(requests) == 1


def test_compressed_prefix_timeout_reports_wire_bytes_without_claiming_decoded_body(tmp_path):
    class GzipHeaderThenTimeout(httpx.SyncByteStream):
        def __iter__(self):
            # A complete gzip header has no decoded bytes. Transport still received data.
            yield bytes.fromhex("1f8b0800000000000003")
            raise httpx.ReadTimeout("private-proxy-details-must-not-leak")

    adapter = Hongguo(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200, headers={"Content-Encoding": "gzip"}, stream=GzipHeaderThenTimeout()
                )
            )
        ),
        tmp_path / "gate.json",
    )
    reply = adapter.fetch("hongguo.board", {"board": "hot-drama"}, maximum=20)
    capture = json.loads(reply.raw_text)["capture"]
    assert reply.error == "SOURCE_UNAVAILABLE"
    assert reply.outcome == "network_error"
    assert capture["received_wire_bytes"] == 10
    assert capture["received_bytes"] == 0 and capture["saved_bytes"] == 0
    assert capture["body_complete"] is False and capture["text_available"] is False
    assert capture["failure_kind"] == "transfer_error"
    assert capture["exception_type"] == "ReadTimeout"
    assert "private-proxy-details" not in reply.raw_text


def test_saved_http_base64_read_compatibility_preserves_nul_and_rejects_tamper():
    import base64
    import hashlib

    body = html(count=1) + "\x00"
    envelope = {
        "format": "hongguo-saved-http-v1",
        "response_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "html_base64": base64.b64encode(body.encode()).decode(),
        "capture": {},
    }
    assert response_html(json.dumps(envelope)) == body
    assert len(normalize_board(json.dumps(envelope), "hot-drama").records) == 1
    for change in ({"html_base64": "!!!"}, {"response_sha256": "0" * 64}, {"extra": True}):
        with pytest.raises(AdapterError):
            response_html(json.dumps({**envelope, **change}))
