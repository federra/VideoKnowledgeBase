"""Desktop female catalog structure, with synthetic public-only HTML."""

import pytest

from app.connectors.redfox import AdapterError


def overview(links=None):
    links = links or (
        '<a href="//www.qdmm.com/rank/">人气榜单</a>'
        '<a href="//www.qdmm.com/rank/yuepiao/">月票榜</a>'
        '<a href="//www.qdmm.com/rank/readindex/">阅读指数榜</a>'
    )
    return (
        "<html><head><title>女生小说人气排行榜单-起点女生网</title></head>"
        '<body><div class="rank-nav-list fl"><ul><li>'
        + links
        + '</li></ul></div><div class="rank-body"><div class="rank-list">'
        '<h3>原创风云榜<a href="//www.qdmm.com/rank/yuepiao/chanId0/">更多</a></h3>'
        '<li data-rid="1"><a href="//www.qdmm.com/book/123/">预览作品</a></li>'
        "</div></div></body></html>"
    )


def test_desktop_catalog_uses_navigation_not_preview_or_book_links():
    from app.connectors.qidian_desktop import discover

    rows = discover(overview())
    assert [(v["rank_type"], v["rank_name"]) for v in rows] == [
        ("yuepiao", "月票榜"),
        ("readindex", "阅读指数榜"),
    ]
    assert rows[0]["code"] == "qidian:desktop:female:yuepiao"
    assert rows[0]["source_url"] == "https://www.qdmm.com/rank/yuepiao/"
    assert rows[0]["gender"] == "female"


@pytest.mark.parametrize(
    "links",
    [
        '<a href="https://example.com/rank/yuepiao/">月票榜</a>',
        '<a href="//www.qidian.com/rank/yuepiao/">月票榜</a>',
        '<a href="javascript:alert(1)">月票榜</a>',
        '<a href="//www.qdmm.com/rank/yuepiao/?page=2">月票榜</a>',
        (
            '<a href="//www.qdmm.com/rank/yuepiao/">月票榜</a>'
            '<a href="//www.qdmm.com/rank/yuepiao/">不同榜</a>'
        ),
    ],
)
def test_desktop_catalog_rejects_untrusted_or_ambiguous_navigation(links):
    from app.connectors.qidian_desktop import discover

    with pytest.raises(AdapterError):
        discover(overview(links))


def test_desktop_catalog_rejects_challenge_and_unrelated_pages():
    from app.connectors.qidian_desktop import discover

    for html in (
        "<script src='/probe.js'></script>",
        overview().replace("rank-nav-list", "footer"),
    ):
        with pytest.raises(AdapterError):
            discover(html)


def test_saved_capture_has_file_provenance_without_claiming_http_success(tmp_path):
    from app.connectors.qidian_desktop import inspect_saved_catalog

    path = tmp_path / "female-rank.html"
    path.write_text(overview(), encoding="utf-8")
    value = inspect_saved_catalog(path)
    assert value["capture_kind"] == "user_saved_html"
    assert value["http_status"] is None
    assert value["board_count"] == 2
    assert value["published_books"] == 0
    assert len(value["sha256"]) == 64
    with pytest.raises(AdapterError):
        path.write_bytes(b"\xff")
        inspect_saved_catalog(path)


def ranking(items=None):
    item = (
        '<li data-rid="1"><div class="book-img-box"><span class="rank-tag no1">1</span></div>'
        '<div class="book-mid-info"><h2><a href="//www.qdmm.com/book/123/" data-bid="123">真书名</a></h2>'
        '<p class="author"><a class="name">作者</a><a href="//www.qdmm.com/xhyq">玄幻言情</a>'
        '<a class="go-sub-type">异世大陆</a></p><p class="intro">原始简介</p></div>'
        '<div class="book-right-info"><div class="total"><p><style>do not include CSS</style>'
        '<span class="custom-font">&#100436;</span>月票</p></div></div></li>'
    )
    return overview().replace(
        '<div class="rank-body">',
        '<div class="rank-header"><h3>月票榜</h3><div class="rank-toolbar-wrap" data-year="2026" data-month="10"><a class="act" data-filter-key="chanId" data-filter-value="-1">全部</a></div></div>'
        '<div class="rank-body"><div id="book-img-text" class="book-img-text"><ul>'
        + (items if items is not None else item)
        + '</ul></div><div id="page-container" data-page="1"></div>',
    )


def test_desktop_rank_preserves_actual_rank_and_missing_reader_gender():
    from app.connectors.qidian_desktop import discover, normalize

    board = discover(overview())[0]
    batch = normalize(board, ranking())
    value = batch.records[0]
    meta = value["content"]["source_tags"][0]
    assert value["provider_rank"] == 1 and value["platform_content_id"] == "123"
    assert value["content"]["description"] == "原始简介"
    assert meta["reader_count"] is None and meta["work_fields"]["gender"] is None
    assert meta["work_fields"]["genres"] == ["玄幻言情", "异世大陆"]
    assert meta["taxonomy"] == ["玄幻言情"]
    assert meta["ranking_value_encoded"] is True
    assert "CSS" not in meta["ranking_value_raw"]
    assert meta["ranking_period"] == {"year": "2026", "month": "10"}


@pytest.mark.parametrize(
    "mode",
    ["overview", "page2", "category", "wrongrank", "duplicate", "bad_rank", "foreignbook", "empty"],
)
def test_desktop_rank_rejects_wrong_scope_or_invalid_members(mode):
    from app.connectors.qidian_desktop import discover, normalize

    html = ranking()
    if mode == "overview":
        html = overview()
    elif mode == "page2":
        html = html.replace('data-page="1"', 'data-page="2"')
    elif mode == "category":
        html = html.replace('data-filter-value="-1"', 'data-filter-value="21"')
    elif mode == "wrongrank":
        html = html.replace('class="act"', "")  # active link is added below
        html = html.replace('class="rank-header"><h3>月票榜', 'class="rank-header"><h3>收藏榜')
    elif mode == "duplicate":
        import re

        li = re.search(r'<li data-rid="1">.*?</li>', html)[0]
        html = html.replace(
            '</ul></div><div id="page-container"', li + '</ul></div><div id="page-container"'
        )
    elif mode == "bad_rank":
        html = html.replace('rank-tag no1">1', 'rank-tag no1">0')
    elif mode == "foreignbook":
        html = html.replace(
            'href="//www.qdmm.com/book/123/" data-bid', 'href="//example.com/book/123/" data-bid'
        )
    elif mode == "empty":
        html = ranking("")
    with pytest.raises(AdapterError):
        normalize(discover(overview())[0], html)


def test_desktop_rank_never_imports_more_than_thirty_members():
    import re

    from app.connectors.qidian_desktop import discover, normalize

    item = re.search(r'<li data-rid="1">.*?</li>', ranking())[0]
    items = "".join(
        item.replace('data-rid="1"', f'data-rid="{i}"')
        .replace('rank-tag no1">1', f'rank-tag no1">{i}')
        .replace("/book/123/", f"/book/{i}/")
        .replace('data-bid="123"', f'data-bid="{i}"')
        for i in range(1, 36)
    )
    batch = normalize(discover(overview())[0], ranking(items))
    assert len(batch.records) == 30 and batch.records[-1]["provider_rank"] == 30
    assert batch.returned_items == 35
