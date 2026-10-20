"""Native accessibility evidence: never invent links removed by the UI tool."""

import json

import pytest

from app.connectors.redfox import AdapterError


def capture():
    return json.dumps(
        {
            "capture_kind": "browser_native_accessibility",
            "url": "https://www.qdmm.com/rank/hotsales/",
            "captured_at": "2026-10-20T08:00:00+00:00",
            "page": 1,
            "body": "0 HTML 内容 女生小说畅销排行榜单-起点女生网, URL: …\n\t1 link 畅销榜, Value: qdmm.com/rank/hotsales/\n\t2 标题 畅销榜, Value: 3\n\t3 link 全部, Value: javascript:\n\t4 内容列表\n\t\t5 container\n\t\t\t6 文本 1\n\t\t\t7 link 真实书名在线阅读, Value: qdmm.com/book/123/\n\t\t\t8 标题 真实书名, Value: 2\n\t\t\t\t9 link 真实书名, Help: 真实书名最新章节在线阅读, Value: qdmm.com/book/123/\n\t\t\t10 link 作者, Value: qdmm.com/author/456/\n\t\t\t11 link 玄幻言情, Value: qdmm.com/xhyq\n\t\t\t12 link 异世大陆, Value: qdmm.com/all/chanId84-subCateId844/\n\t\t\t13 text 连载 真实简介\n\t\t\t14 container\n\t\t\t\t15 text 𘟁𘟅 推荐\n\t\t16 container\n\t\t\t17 文本 2\n\t\t\t18 link 截断链接书在线阅读, Value: …\n\t\t\t19 标题 截断链接书\n\t\t\t\t20 link 截断链接书, Value: …\n\t21 文本栏 (settable) 1",
        },
        ensure_ascii=False,
    )


def test_browser_rank_keeps_verified_prefix_and_encoded_metric_without_inference():
    from app.connectors.qidian_browser import discover, normalize

    board = discover(capture())[0]
    batch = normalize(board, capture())
    assert batch.returned_items == 2 and len(batch.records) == 1
    item = batch.records[0]
    assert item["platform_content_id"] == "123" and item["provider_rank"] == 1
    assert item["content"]["description"] == "真实简介"
    meta = item["content"]["source_tags"][0]
    assert meta["reader_count"] is None and meta["work_fields"]["gender"] is None
    assert meta["work_fields"]["genres"] == ["玄幻言情", "异世大陆"]
    assert meta["ranking_value_raw"] == "𘟁𘟅 推荐"
    assert board["method"] == "qidian-browser-ax-v1"


def test_readindex_preserves_page_order_when_site_has_no_explicit_rank_text():
    from app.connectors.qidian_browser import discover, normalize

    text = capture().replace("hotsales", "readindex").replace("畅销榜", "阅读指数榜")
    text = text.replace("\\t\\t\\t6 文本 1\\n", "").replace("\\t\\t\\t17 文本 2\\n", "")
    batch = normalize(discover(text)[0], text)
    assert batch.records[0]["provider_rank"] == 1
    assert batch.records[0]["content"]["source_tags"][0]["ranking_position_basis"] == "page_order"


def test_book_link_host_must_be_exact_not_a_lookalike():
    from app.connectors.qidian_browser import discover, normalize

    text = capture().replace("qdmm.com/book/", "qdmmXcom/book/")
    with pytest.raises(AdapterError):
        normalize(discover(text)[0], text)


def test_qidian_rank_options_use_current_channel_names_and_distinguish_duplicate_labels():
    from app.intelligence.novels import rank_options

    boards = [
        {"platform": "qidian", "gender": "male", "rank_type": "rec", "rank_name": "推荐榜"},
        {"platform": "qidian", "gender": "female", "rank_type": "recom", "rank_name": "推荐榜"},
        {"platform": "qidian", "gender": "female", "rank_type": "readindex", "rank_name": "阅读指数榜"},
        {"platform": "qidian", "gender": "male", "rank_type": "readindex", "rank_name": "阅读榜"},
    ]
    assert rank_options(boards, "female") == [
        {"value": "readindex", "label": "阅读指数榜"},
        {"value": "rec", "label": "推荐榜 · 男频"},
        {"value": "recom", "label": "推荐榜 · 女频"},
    ]


@pytest.mark.parametrize(
    "mode", ["host", "page", "title", "rank", "mismatch", "empty", "kind", "time"]
)
def test_browser_capture_rejects_wrong_scope_or_broken_identity(mode):
    from app.connectors.qidian_browser import discover, normalize

    original = capture()
    board = discover(original)[0]
    d = json.loads(original)
    if mode == "host":
        d["url"] = "https://example.com/rank/hotsales/"
    if mode == "page":
        d["page"] = 2
    if mode == "title":
        d["body"] = d["body"].replace("标题 畅销榜", "标题 收藏榜")
    if mode == "rank":
        d["body"] = d["body"].replace("文本 1", "文本 2")
    if mode == "mismatch":
        d["body"] = d["body"].replace(
            "真实书名最新章节在线阅读, Value: qdmm.com/book/123/",
            "真实书名最新章节在线阅读, Value: qdmm.com/book/999/",
        )
    if mode == "empty":
        d["body"] = "0 HTML 内容 安全验证-起点女生网"
    if mode == "kind":
        d["capture_kind"] = "user_saved_html"
    if mode == "time":
        d["captured_at"] = "not a timestamp"
    with pytest.raises(AdapterError):
        normalize(board, json.dumps(d, ensure_ascii=False))
