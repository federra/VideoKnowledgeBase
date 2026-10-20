"""NovelCrawler method, independently implemented. Only synthetic public transport."""

import json

import httpx
import pytest


def page(records=None, *, catalog=False, gender="male"):
    data = {
        "gender": gender,
        "pageNum": 1,
        "records": records
        if records is not None
        else [
            {
                "bid": "123",
                "bName": "真书名",
                "bAuth": "作者",
                "cat": "玄幻",
                "subCat": "东方玄幻",
                "rankNum": 1,
                "rankCnt": "1.2万月票",
                "desc": "来源简介",
            }
        ],
        "filters": [
            {
                "key": "catId",
                "items": [{"text": "全站", "value": -1}, {"text": "玄幻", "value": 21}],
            }
        ],
    }
    pc = {
        "_pageId": "/src/pages/rank/index" if catalog else "/src/pages/rankDetail/index",
        "hostname": "m.qidian.com" if gender == "male" else "m.qdmm.com",
        "routeParams": {"gender": gender, "pageType": "yuepiao"},
        "pageProps": {"pageData": data},
    }
    return (
        '<script type="application/json">'
        + json.dumps({"pageContext": pc}, ensure_ascii=False)
        + "</script>"
    )


def board():
    return {
        "platform": "qidian",
        "rank_type": "yuepiao",
        "rank_name": "月票榜",
        "gender": "male",
        "category_id": "all",
        "category_name": "全站",
        "code": "qidian:mobile:male:yuepiao",
        "method": "novelcrawler-mobile-v1",
    }


def test_qidian_catalog_discovers_actual_links_not_reference_aliases():
    from app.connectors.qidian_mobile import discover

    html = (
        page(catalog=True)
        + '<span>月票榜</span><a href="//m.qidian.com/rank/yuepiao/">更多</a><span>推荐榜</span><a href="//m.qidian.com/rank/rec/">更多</a><a href="https://example.com/rank/evil/">ignore</a>'
    )
    rows = discover(html, "male")
    assert [(b["rank_type"], b["rank_name"]) for b in rows] == [
        ("yuepiao", "月票榜"),
        ("rec", "推荐榜"),
    ]
    assert all(b["code"].startswith("qidian:mobile:male:") for b in rows)


def test_qidian_metrics_and_work_fields_do_not_inherit_board_gender():
    from app.connectors.qidian_mobile import normalize

    batch = normalize(board(), page())
    record = batch.records[0]
    meta = record["content"]["source_tags"][0]
    assert record["platform_content_id"] == "123" and meta["title"] == "真书名"
    assert meta["reader_count"] is None and meta["ranking_value_raw"] == "1.2万月票"
    assert meta["work_fields"] == {"gender": None, "genres": ["玄幻", "东方玄幻"]} and meta[
        "taxonomy"
    ] == ["玄幻"]
    assert "月票" not in record["content"]["description"]


def test_qidian_bounds_and_route_identity():
    from app.connectors.qidian_mobile import normalize

    books = [{"bid": str(i), "bName": "作品" + str(i), "rankNum": i + 1} for i in range(35)]
    assert len(normalize(board(), page(books)).records) == 30
    with pytest.raises(ValueError):
        normalize(board(), page(gender="female"))


@pytest.mark.parametrize("status", [202, 403])
def test_qidian_mobile_failures_remain_replies(status):
    from app.connectors.qidian_mobile import QidianMobile

    calls = []

    def transport(r):
        calls.append(r)
        return httpx.Response(status, text="challenge")

    reply = QidianMobile(httpx.Client(transport=httpx.MockTransport(transport))).fetch(
        "novel.qidian.board", board(), maximum=30
    )
    assert reply.error and reply.batch is None and reply.http_status == status and len(calls) == 1
    assert str(calls[0].url) == "https://m.qidian.com/rank/yuepiao/"
    assert "iPhone" in calls[0].headers["User-Agent"]


def test_qidian_empty_malformed_and_arbitrary_book_links_fail_closed():
    from app.connectors.qidian_mobile import QidianMobile

    for text in [
        '<a href="/book/123/">推荐书</a>',
        page([None]),
        page().replace('"records":', '"notRecords":'),
    ]:
        reply = QidianMobile(
            httpx.Client(
                transport=httpx.MockTransport(lambda r, text=text: httpx.Response(200, text=text))
            )
        ).fetch("novel.qidian.board", board(), maximum=30)
        assert reply.error and reply.raw_text == text


@pytest.mark.parametrize("mode", ["oversize", "decode", "interrupted"])
def test_qidian_keeps_bounded_received_evidence_on_read_failures(mode):
    import base64

    from app.connectors.qidian_mobile import QidianMobile

    class Partial(httpx.SyncByteStream):
        def __iter__(self):
            yield b"challenge-prefix"
            raise httpx.ReadError("connection interrupted")

    response = (
        httpx.Response(403, content=b"challenge-prefix" + b"x" * (3 * 1024 * 1024))
        if mode == "oversize"
        else httpx.Response(200, content=b"challenge-prefix\xff")
        if mode == "decode"
        else httpx.Response(200, stream=Partial())
    )
    reply = QidianMobile(httpx.Client(transport=httpx.MockTransport(lambda r: response))).fetch(
        "novel.qidian.board", board(), maximum=30
    )
    assert reply.error and reply.batch is None
    if mode == "decode":
        assert "[invalid UTF-8; base64 body]" in reply.raw_text
        assert base64.b64encode(b"challenge-prefix\xff").decode() in reply.raw_text
    else:
        assert reply.raw_text.startswith("challenge-prefix")
        assert (
            "[truncated" in reply.raw_text
            if mode == "oversize"
            else "[incomplete" in reply.raw_text
        )
    if mode == "oversize":
        assert reply.http_status == 403 and reply.outcome == "http_error"
        assert len(reply.raw_text) < 3 * 1024 * 1024 + 100
