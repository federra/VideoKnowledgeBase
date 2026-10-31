import pytest

from app.connectors import douyin_search as ds
from app.connectors.redfox import AdapterError
from tests.test_douyin_posts import NOW, post


def wrapped(rows, offset=0, cursor=20, more=1, search_id="query-id"):
    return {
        "kind": "search",
        "parameters": {
            "keyword": "微电影",
            "search_channel": "aweme_video_web",
            "offset": str(offset),
            "count": "20",
            "sort_type": "0",
            "search_id": "" if offset == 0 else "query-id",
        },
        "body": {
            "status_code": 0,
            "data": [{"aweme_info": r} for r in rows],
            "cursor": cursor,
            "has_more": more,
            "extra": {"logid": search_id},
        },
    }


def test_comprehensive_order_not_likes_and_fifty_unique_video_cap():
    pages = [
        wrapped([post(i, NOW, str(i)) for i in range(n, n + 20)], offset=n - 1, cursor=n + 19)
        for n in (1, 21, 41)
    ]
    batch, complete = ds.combine(pages)
    assert len(batch.records) == 50 and complete
    assert [r["platform_content_id"] for r in batch.records[:3]] == ["1", "2", "3"]
    assert batch.records[0]["content"]["like_count"] == 1
    assert batch.records[0]["content"]["source_tags"][-1]["kind"] == ds.POLICY


def test_partial_keeps_only_acquired_prefix_and_does_not_fabricate_fifty():
    batch, complete = ds.combine([wrapped([post(2, NOW, 999), post(1, NOW, None)])])
    assert not complete
    assert [x["platform_content_id"] for x in batch.records] == ["2", "1"]
    assert batch.records[1]["content"]["like_count"] is None


def test_wrong_sort_keyword_cursor_or_channel_rejected():
    for key, value in [
        ("keyword", "电影"),
        ("sort_type", "1"),
        ("search_channel", "aweme_general"),
        ("offset", "20"),
    ]:
        body = wrapped([post(1, NOW)])
        body["parameters"][key] = value
        with pytest.raises(AdapterError):
            ds.combine([body])


def test_image_filter_and_duplicate_never_invent_new_positions():
    body = wrapped(
        [post(1, NOW), post(1, NOW), post(2, NOW, aweme_type=68, images=[{}]), post(3, NOW)], more=0
    )
    batch, complete = ds.combine([body])
    assert complete and [r["platform_content_id"] for r in batch.records] == ["1", "3"]


def test_search_session_chain_and_conflicting_sort_cannot_mix_results():
    first = wrapped([post(1, NOW)])
    second = wrapped([post(2, NOW)], offset=20, cursor=40)
    second["parameters"]["search_id"] = "another-query"
    with pytest.raises(AdapterError):
        ds.combine([first, second])
    first["parameters"].update(sort_type="1", filter_selected='{"sort_type":"0"}')
    with pytest.raises(AdapterError):
        ds.combine([first])


@pytest.mark.parametrize(
    "data", [[None], ["bad"], [{"aweme_info": "bad"}], [{"aweme_info": {"author": []}}]]
)
def test_bad_nested_shapes_are_adapter_errors(data):
    value = wrapped([])
    value["body"]["data"] = data
    with pytest.raises(AdapterError):
        ds.search_page(value)


def test_refresh_channel_plan_keeps_creator_only_and_story_search_separate():
    from app.intelligence.refresh_worker import channel_names

    assert channel_names({"business": "story_short", "creators_only": True, "creators": [{}]}) == (
        "creators",
    )
    assert channel_names({"business": "story_short", "creators": []}) == (
        "hongguo",
        "tikhub",
        "fanqie",
        "qidian",
        "microfilm",
    )
    assert "microfilm" not in channel_names({"business": "motion_comic", "creators": []})
