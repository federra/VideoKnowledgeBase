import pytest

from app.connectors import douyin_series as ds
from app.connectors.redfox import AdapterError


def series(n, plays):
    return {
        "series_id": str(n),
        "series_name": f"短剧{n}",
        "desc": "简介",
        "author": {"uid": "123456", "sec_uid": "MS4w_test", "nickname": "作者"},
        "stats": {"play_vv": plays, "collect_vv": 2},
        "series_content_types": [{"name": "爱情"}],
    }


def page(rows, cursor=0, more=0):
    return {"status_code": 0, "series_infos": rows, "cursor": cursor, "has_more": more}


def test_top_requires_complete_cursor_chain_including_empty_middle_pages():
    pages = [
        (0, page([series(1, 96000)], 20, 1)),
        (20, page(None, 10, 1)),
        (10, page([series(2, 326000)], 0, 0)),
    ]
    assert [r["platform_content_id"] for r in ds.top(pages, "MS4w_test", "123456").records] == [
        "series:2",
        "series:1",
    ]
    with pytest.raises(AdapterError):
        ds.top(pages[:-1], "MS4w_test", "123456")
    with pytest.raises(AdapterError):
        ds.top([(0, page([], 0, 1))], "MS4w_test", "123456")


def test_creator_binding_and_missing_play_metric_cannot_fabricate_top():
    with pytest.raises(AdapterError):
        ds.top([(0, page([series(1, 10)]))], "another", "123456")
    with pytest.raises(AdapterError):
        ds.top([(0, page([series(1, None)]))], "MS4w_test", "123456")
    rows = [series(n, n) for n in range(15)]
    result = ds.top([(0, page(rows))], "MS4w_test", "123456")
    assert len(result.records) == 10
    assert result.records[0]["content"]["view_count"] == 14
    assert result.records[0]["content"]["like_count"] is None


def test_first_episode_requires_explicit_index_series_and_owner():
    a = {
        "aweme_id": "222",
        "series_info": {"series_id": "999"},
        "author": {"uid": "123456"},
        "series_play_info": {"series_aweme_index": 2},
    }
    b = {**a, "aweme_id": "111", "series_play_info": {"series_aweme_index": 1}}
    assert ds.first_episode({"status_code": 0, "aweme_list": [a, b]}, "999", "123456") == "111"
    with pytest.raises(AdapterError):
        ds.first_episode({"status_code": 0, "aweme_list": [a]}, "999", "123456")
    with pytest.raises(AdapterError):
        ds.first_episode({"status_code": 0, "aweme_list": [b]}, "other", "123456")


def test_comments_never_cross_video_or_exceed_fifteen():
    rows = [
        {
            "cid": str(i),
            "aweme_id": "111",
            "text": f"评论{i}",
            "digg_count": i,
            "create_time": 1700000000,
            "user": {"nickname": "观众"},
        }
        for i in range(20)
    ]
    result = ds.comments({"status_code": 0, "comments": rows}, "111")
    assert len(result) == 15
    assert result[0]["platform_comment_id"] == "0"
    rows[0]["aweme_id"] = "other"
    with pytest.raises(AdapterError):
        ds.comments({"status_code": 0, "comments": rows}, "111")


def test_identity_only_uses_directory_author_not_recommendations():
    assert ds.catalog_identity(page([series(1, 10)]), "MS4w_test")["uid"] == "123456"
    with pytest.raises(AdapterError):
        ds.catalog_identity({"status_code": 0, "recommended": [series(1, 10)]}, "MS4w_test")
