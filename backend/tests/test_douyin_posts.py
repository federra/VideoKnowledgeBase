from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.connectors import douyin_posts as dp
from app.connectors.redfox import AdapterError

SH = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 25, 20, tzinfo=SH)
START = datetime(2026, 10, 18, tzinfo=SH)


def post(i, when, likes=0, **extra):
    return {
        "aweme_id": str(i),
        "create_time": int(when.timestamp()),
        "desc": f"视频{i}",
        "aweme_type": 0,
        "video": {"play_addr": {"uri": "video"}},
        "is_top": 0,
        "author": {"uid": "123456", "sec_uid": "MS4w_test", "nickname": "博主"},
        "statistics": {
            "digg_count": likes,
            "comment_count": None,
            "collect_count": 2,
            "share_count": 3,
        },
        **extra,
    }


def page(rows, cursor=0, more=0):
    return {"status_code": 0, "aweme_list": rows, "max_cursor": cursor, "has_more": more}


def test_shanghai_calendar_window_not_rolling_168h():
    assert dp.window(NOW) == {"start": START.isoformat(), "end": NOW.isoformat()}
    assert dp.window(NOW.astimezone(ZoneInfo("UTC"))) == dp.window(NOW)


def test_window_inclusive_metrics_numeric_null_and_no_top_ten_limit():
    rows = [post(i, START, str(i)) for i in range(1, 16)]
    rows += [
        post(98, datetime(2026, 10, 17, 23, 59, 59, tzinfo=SH), 999),
        post(99, datetime(2026, 10, 25, 20, 0, 1, tzinfo=SH), 999),
    ]
    rows += [post(100, NOW, None)]
    b = dp.combine([(0, page(rows))], "MS4w_test", "123456", dp.window(NOW))
    assert len(b.records) == 16
    assert [r["platform_content_id"] for r in b.records[:3]] == ["15", "14", "13"]
    assert b.records[-1]["content"]["like_count"] is None
    assert b.records[0]["content"]["comment_count"] is None
    assert b.records[0]["content"]["published_at"] == START


def test_pinned_old_video_does_not_end_recent_window():
    old = post(1, datetime(2020, 1, 1, tzinfo=SH), is_top=1)
    first = page([old, post(2, NOW)], int(NOW.timestamp() * 1000), 1)
    with pytest.raises(AdapterError):
        dp.combine([(0, first)], "MS4w_test", "123456", dp.window(NOW))
    end = page(
        [post(3, START), post(4, datetime(2026, 10, 17, tzinfo=SH))],
        int(datetime(2026, 10, 17, tzinfo=SH).timestamp() * 1000),
        1,
    )
    b = dp.combine([(0, first), (first["max_cursor"], end)], "MS4w_test", "123456", dp.window(NOW))
    assert len(b.records) == 2


def test_unordered_old_cursor_cycle_wrong_author_or_future_cursor_rejected():
    for rows, cursor in [([post(1, NOW), post(2, START)], 1), ([post(1, NOW)], 0)]:
        with pytest.raises(AdapterError):
            dp.combine([(0, page(rows, cursor, 1))], "MS4w_test", "123456", dp.window(NOW))
    with pytest.raises(AdapterError):
        dp.combine([(0, page([post(1, NOW)]))], "other", "123456", dp.window(NOW))


def test_profile_identity_matches_exact_requested_creator():
    body = {"status_code": 0, "user": {"uid": "123456", "sec_uid": "MS4w_test", "nickname": "博主"}}
    assert (
        dp.parse_identity(__import__("json").dumps(body), "https://www.douyin.com/user/MS4w_test")[
            "name"
        ]
        == "博主"
    )
    with pytest.raises(AdapterError):
        dp.parse_identity(__import__("json").dumps(body), "https://www.douyin.com/user/other")


def test_timestamp_timezone_origin_and_first_line_title():
    p = post(1, NOW)
    p["desc"] = "标题\n完整介绍"
    r = dp.normalize_page(page([p]), "MS4w_test", "123456").records[0]
    assert r["content"]["publish_timezone"] == "UTC"
    assert r["display_name"] == "标题"
    assert r["content"]["description"] == "标题\n完整介绍"


def test_image_posts_are_excluded_without_ending_pagination():
    image = post(9, NOW, 999999, aweme_type=68, images=[{"uri": "image"}])
    first = page([image], int(NOW.timestamp() * 1000), 1)
    with pytest.raises(AdapterError):
        dp.combine([(0, first)], "MS4w_test", "123456", dp.window(NOW))
    result = dp.combine(
        [(0, first), (first["max_cursor"], page([post(10, START, 1)]))],
        "MS4w_test",
        "123456",
        dp.window(NOW),
    )
    assert [r["platform_content_id"] for r in result.records] == ["10"]


def test_identity_can_use_latest_exact_author_posts_but_not_recommendations():
    import json

    assert (
        dp.parse_identity(
            json.dumps(page([post(1, NOW)])), "https://www.douyin.com/user/MS4w_test"
        )["name"]
        == "博主"
    )
    with pytest.raises(AdapterError):
        dp.parse_identity(json.dumps(page([post(1, NOW)])), "https://www.douyin.com/user/other")
