"""Novel public adapters. Synthetic payloads, no paid/provider requests."""

import json

import httpx
import pytest


def board():
    return {
        "platform": "fanqie",
        "rank_type": "read",
        "gender": "male",
        "category_id": "8",
        "category_name": "科幻末世",
        "rank_version": "123",
        "font_sha256": "a" * 64,
    }


def test_catalog_preserves_gender_identity_and_all_boards():
    from app.connectors.novels import catalog

    state = {
        "rank": {
            "rankVersion": "123",
            "rankCategoryTypeList": {
                "male": [{"id": "8", "name": "科幻"}],
                "female": [{"id": "8", "name": "科幻"}],
            },
        }
    }
    result = catalog("<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>")
    assert len(result) == 4 and len({b["code"] for b in result}) == 4


def test_books_are_capped_decoded_and_missing_is_not_zero():
    from app.connectors.novels import normalize

    records = [
        {
            "bookId": str(n),
            "bookName": "书" + str(n),
            "author": "作者",
            "abstract": "简介",
            "read_count": 0 if n == 0 else None,
            "currentPos": n + 1,
        }
        for n in range(35)
    ]
    result = normalize(board(), {"code": 0, "data": {"book_list": records}}, decoder={})
    assert len(result.records) == 30
    meta = result.records[0]["content"]["source_tags"][0]
    assert (
        meta["reader_count"] == 0
        and result.records[1]["content"]["source_tags"][0]["reader_count"] is None
    )
    assert result.records[0]["content"]["view_count"] is None
    with pytest.raises(ValueError):
        normalize(
            board(),
            {"code": 0, "data": {"book_list": [{"bookId": "1", "bookName": "\ue3e8"}]}},
            decoder={},
        )


@pytest.mark.parametrize("status", [202, 403])
def test_qidian_challenge_is_not_empty_ranking(status):
    from app.connectors.novels import PublicNovels

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status, text="<title>WAF拦截页面</title>")
        )
    )
    reply = PublicNovels(client).fetch("novel.qidian.catalog", {}, maximum=30)
    assert reply.error and reply.batch is None and reply.http_status == status


def test_only_fixed_public_urls_and_thirty_limit():
    from app.connectors.novels import PublicNovels

    seen = []

    def handle(r):
        seen.append(r)
        return httpx.Response(200, json={"code": 0, "data": {"book_list": []}})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    reply = PublicNovels(client, decoder={}).fetch("novel.fanqie.board", board(), maximum=30)
    assert not reply.error
    assert seen[0].url.params["limit"] == "30" and seen[0].url.params["offset"] == "0"
    with pytest.raises(ValueError):
        PublicNovels(client).fetch("novel.fanqie.board", board(), maximum=31)


def test_qidian_unverified_html_with_recommendations_is_rejected():
    from app.connectors.novels import PublicNovels

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text='<a href="/book/123/">推荐书</a>')
        )
    )
    reply = PublicNovels(client).fetch("novel.qidian.board", {"rank_type": "hotsales"}, maximum=30)
    assert reply.error and reply.batch is None


def test_current_font_is_discovered_in_inline_style_not_only_linked_css():
    from scripts.collect_novels import font_urls

    assert font_urls(
        "<style>@font-face{font-family:a;src:url(https://lf6-awef.bytetos.com/obj/awesome-font/c/current.otf);font-weight:400}</style>"
    ) == ["https://lf6-awef.bytetos.com/obj/awesome-font/c/current.otf"]


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "data": None},
        {"code": 0, "data": {"book_list": [None]}},
        {"code": 0, "data": {"book_list": [[]]}},
    ],
)
def test_malformed_json_still_returns_failure_reply_with_original_body(payload):
    from app.connectors.novels import PublicNovels

    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    )
    reply = PublicNovels(client, decoder={}).fetch("novel.fanqie.board", board(), maximum=30)
    assert (
        reply.error and reply.outcome == "invalid_shape" and json.loads(reply.raw_text) == payload
    )


@pytest.mark.parametrize(
    "state",
    [
        None,
        {"rank": None},
        {"rank": {"rankVersion": "123", "rankCategoryTypeList": {"male": [None], "female": []}}},
    ],
)
def test_malformed_catalog_returns_failure_reply(state):
    from app.connectors.novels import PublicNovels

    text = "<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=text)))
    reply = PublicNovels(client).fetch("novel.fanqie.catalog", {}, maximum=30)
    assert reply.error and reply.raw_text == text


def test_font_verification_rejects_known_and_unknown_font_mix(monkeypatch, tmp_path):
    import hashlib

    from scripts import collect_novels as script

    known = b"known"
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, content=known if r.url.path.endswith("old.otf") else b"changed"
            )
        )
    )
    monkeypatch.setattr(script.httpx, "Client", lambda **kw: client)
    monkeypatch.setattr(script, "spec", lambda: {"font_sha256": hashlib.sha256(known).hexdigest()})
    html = "".join(
        "@font-face{font-weight:400;src:url(https://lf6-awef.bytetos.com/obj/awesome-font/c/"
        + name
        + ".otf)}"
        for name in ["old", "new"]
    )
    with pytest.raises(RuntimeError):
        script.verify_font(html, tmp_path)


def test_work_labels_never_inherit_rank_membership_or_guess_category():
    from app.connectors.novels import book_fields

    assert book_fields({"curent_category_id": 8, "pos_category_id": 8}, decoder={}) == {
        "gender": None,
        "genres": [],
    }
    assert book_fields(
        {"gender": "female", "categoryV2": "科幻末世", "category": "都市"}, decoder={}
    ) == {"gender": "female", "genres": ["科幻末世", "都市"]}
    assert book_fields({"gender": 1, "categoryV2": None, "category": []}, decoder={}) == {
        "gender": None,
        "genres": [],
    }
