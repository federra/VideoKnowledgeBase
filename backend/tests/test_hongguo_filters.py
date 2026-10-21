from app.intelligence.video_filters import filter_hongguo


def item(board, tags, host="hongguoduanju.com"):
    return {
        "source_name": board,
        "genre_tags": tags,
        "entry": {"observation": {"original_url": f"https://{host}/detail?series_id=1"}},
    }


def test_filters_use_real_membership_and_labels_before_paging():
    rows = [
        item("AI剧热播榜", ["都市", "逆袭"]),
        item("漫剧热播榜", ["玄幻"]),
        item("AI剧热播榜", ["假题材"], "example.com"),
    ]
    values, genres = filter_hongguo(rows, "hot-ai-drama", "都市")
    assert values == rows[:1]
    assert genres == ["都市", "逆袭"]
    assert filter_hongguo(rows, "hot-real-drama", None) == ([], [])
    assert filter_hongguo(rows, None, None)[0] == rows[:2]


def test_second_genre_uses_explicit_parent_and_resets_options_by_genre():
    from app.intelligence.video_filters import filter_subgenre

    row = item("AI剧热播榜", [])
    row["genre_hierarchy"] = [
        {"genre": "都市", "subgenres": ["重生"]},
        {"genre": "玄幻", "subgenres": ["修仙"]},
    ]
    assert filter_hongguo([row], None, "都市")[0] == [row]
    assert filter_subgenre([row], "都市", "重生") == ([row], ["重生"])
    assert filter_subgenre([row], "都市", "修仙") == ([], ["重生"])
    assert filter_subgenre([item("AI剧热播榜", ["都市", "重生"])], "都市", None) == (
        [item("AI剧热播榜", ["都市", "重生"])],
        [],
    )
