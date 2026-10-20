"""Business keyword boards rank video content by actual views, never author names or likes."""


def item(ident, text, views, *, author="普通作者", likes="999999"):
    return {
        "source_id": "source",
        "author": author,
        "entry": {
            "id": ident,
            "position": 0,
            "observation": {
                "kind": "content",
                "platform_code": "douyin",
                "platform_id": ident,
                "description": text,
                "view_count": views,
                "like_count": likes,
            },
        },
    }


def test_keyword_board_requires_content_match_and_actual_views():
    from app.intelligence.ranking import keyword_board

    rows = [
        item("author-only", "做饭教程", "999999", author="漫剧作者"),
        item("missing", "漫剧预告", None),
        item("valid", "漫剧正片", "50"),
    ]
    result = keyword_board(rows)
    assert result["status"] == "insufficient_metrics"
    assert result["items"] == []  # Missing values cannot silently yield a false Top.
    assert result["text_matches"] == 2 and result["missing_views"] == 1


def test_keyword_board_numeric_top_ten_never_likes_or_provider_order():
    from app.intelligence.ranking import keyword_board

    rows = [item(str(i), f"漫剧 {i}", str(i), likes=str(99 - i)) for i in range(12)]
    rows.append(item("large", "漫剧", "9007199254740993", likes="0"))
    result = keyword_board(rows)
    assert result["status"] == "ready" and len(result["items"]) == 10
    assert [x["entry"]["id"] for x in result["items"]][:3] == ["large", "11", "10"]
    assert (
        keyword_board([item("zero", "漫剧", "0")])["items"][0]["entry"]["observation"]["view_count"]
        == "0"
    )
    assert (
        keyword_board([item("author-only", "其他正文", "99", author="漫剧")])["status"]
        == "no_content_matches"
    )


def test_legacy_board_snapshot_cannot_bypass_motion_comic_keyword_and_views(monkeypatch):
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.intelligence import feedback, insight, service

    row = item("old", "其他教程", None)
    row.update(source_name="legacy board", account_id=None)
    row["entry"]["observation"].update(observed_at=datetime.now(UTC), comment_count=None)
    monkeypatch.setattr(
        service,
        "selected",
        lambda *a, **kw: [
            ({"view_kind": "board", "source_id": "source", "job_id": "legacy-job"}, [row])
        ],
    )
    monkeypatch.setattr(feedback, "attach_previews", lambda *a: None)
    monkeypatch.setattr(insight, "latest_insight", lambda *a: None)
    monkeypatch.setattr(
        service, "row", lambda *a: {"capability_code": "legacy", "safe_request": {}}
    )
    result = service.feed(None, SimpleNamespace(org_id="org"), "motion_comic", date(2026, 10, 17))
    assert result["items"] == []
    assert result["metrics"]["videos"] is None


def test_legacy_keyword_fill_cannot_spend_again_for_unverified_playback_board(monkeypatch):
    import pytest
    from scripts import fill_redfox_keywords as command

    monkeypatch.setattr("sys.argv", ["fill_redfox_keywords.py", "--execute"])
    monkeypatch.setattr(
        command,
        "registry",
        lambda: pytest.fail("old fill must not construct paid handler"),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="PLAYBACK_RANKING_UNVERIFIED"):
        command.main()


def test_missing_views_uses_only_verified_default_batch_and_keeps_original_positions():
    from app.intelligence.ranking import keyword_board

    candidates = [item("old", "漫剧热榜", None, likes="999999")]
    default = [
        item("second", "漫剧二", None, likes="999"),
        item("first", "漫剧一", None, likes="0"),
    ]
    default[0]["entry"]["position"] = 1
    default[1]["entry"]["position"] = 0
    result = keyword_board(candidates + default, default_rows=default)
    assert result["status"] == "default_order"
    assert [x["entry"]["id"] for x in result["items"]] == ["first", "second"]
    # _4 and ambiguous broad-search results are never passed as a trusted fallback batch.
    assert keyword_board(candidates)["items"] == []
