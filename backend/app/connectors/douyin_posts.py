"""Ordinary creator posts: frozen Shanghai calendar window, API JSON only."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.connectors.douyin_series import checked
from app.connectors.redfox import AdapterError, Batch, number, text

VERSION = "douyin-creator-posts-v1"
CAPABILITY = "douyin.creator.posts"
POLICY = "shanghai-seven-calendar-days-likes-v1"
MAX_PAGES = 60
MAX_ITEMS = MAX_PAGES * 20
SH = ZoneInfo("Asia/Shanghai")


def window(now):
    if now.tzinfo is None:
        raise AdapterError("INVALID_INPUT")
    end = now.astimezone(SH)
    start = (end - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"start": start.isoformat(), "end": end.isoformat()}


def bounds(value):
    try:
        end = datetime.fromisoformat(value["end"])
        expected = window(end)
        if value != expected:
            raise ValueError
        return datetime.fromisoformat(value["start"]), end
    except (ValueError, TypeError, KeyError):
        raise AdapterError("INVALID_INPUT") from None


def parse_identity(raw, url):
    b = checked(json.loads(raw))
    a = b.get("user") or {}
    if not a and isinstance(b.get("aweme_list"), list) and b["aweme_list"]:
        authors = [r.get("author") or {} for r in b["aweme_list"]]
        identities = {(r.get("uid"), r.get("sec_uid")) for r in authors}
        if len(identities) != 1:
            raise AdapterError("INVALID_RESPONSE")
        a = authors[0]
    uid, sec = a.get("uid"), a.get("sec_uid")
    if (
        not isinstance(uid, str)
        or not uid.isascii()
        or not uid.isdecimal()
        or not 3 <= len(uid) <= 25
        or uid.startswith("0")
        or url != "https://www.douyin.com/user/" + str(sec)
    ):
        raise AdapterError("INVALID_RESPONSE")
    return {"uid": uid, "sec_uid": sec, "name": text(a.get("nickname")) or ""}


def normalize_page(body, sec, uid):
    checked(body)
    rows = body.get("aweme_list")
    if rows is None and "aweme_list" in body:
        rows = []
    if (
        not isinstance(rows, list)
        or len(rows) > 20
        or type(body.get("has_more")) is not int
        or body["has_more"] not in (0, 1)
        or type(body.get("max_cursor")) is not int
        or body["max_cursor"] < 0
    ):
        raise AdapterError("INVALID_RESPONSE")
    records = []
    for a in rows:
        author = a.get("author") or {}
        aid = a.get("aweme_id")
        stamp = a.get("create_time")
        if (
            author.get("uid") != uid
            or author.get("sec_uid") != sec
            or not isinstance(aid, str)
            or not aid.isascii()
            or not aid.isdecimal()
            or type(stamp) is not int
            or not 0 < stamp < 32503680000
        ):
            raise AdapterError("INVALID_RESPONSE")
        if (
            a.get("images")
            or a.get("aweme_type") == 68
            or not isinstance(a.get("video"), dict)
            or not a["video"]
        ):
            continue  # Image/live/unsupported records still count for the raw cursor chain.
        stat = a.get("statistics") or {}
        desc = text(a.get("desc"))
        records.append(
            {
                "platform_content_id": aid,
                "platform_uid": uid,
                "account_display_name": text(author.get("nickname")),
                "display_name": desc.splitlines()[0] if desc else None,
                "aliases": [("sec_uid", sec)],
                "content": {
                    "description": desc,
                    "original_url": f"https://www.douyin.com/video/{aid}",
                    "source_type_raw": "ordinary-post",
                    "published_at_raw": str(stamp),
                    "published_at": datetime.fromtimestamp(stamp, SH),
                    "publish_timezone": "UTC",
                    "view_count": None,
                    "like_count": number(stat.get("digg_count")),
                    "comment_count": number(stat.get("comment_count")),
                    "collect_count": number(stat.get("collect_count")),
                    "share_count": number(stat.get("share_count")),
                    "repost_count": None,
                    "source_tags": [{"kind": POLICY, "metric_scope": "video"}],
                },
            }
        )
    return Batch("creator_works", records, len(rows))


def complete(body, frozen):
    start, _ = bounds(frozen)
    if body["has_more"] == 0:
        return True
    # A time cursor is trusted only when it agrees with the oldest non-pinned row.
    # A pinned old work or an unordered page must never truncate the window.
    stamps = [a["create_time"] for a in body["aweme_list"] or [] if a.get("is_top", 0) == 0]
    return bool(
        stamps
        and stamps == sorted(stamps, reverse=True)
        and body["max_cursor"] == min(stamps) * 1000
        and body["max_cursor"] < start.timestamp() * 1000
    )


def combine(pages, sec, uid, frozen):
    start, end = bounds(frozen)
    if not pages or len(pages) > MAX_PAGES:
        raise AdapterError("INVALID_RESPONSE")
    cursor, seen, records, ended = 0, set(), {}, False
    for requested, body in pages:
        if ended or requested != cursor or cursor in seen:
            raise AdapterError("INVALID_RESPONSE")
        seen.add(cursor)
        batch = normalize_page(body, sec, uid)
        for r in batch.records:
            if start <= r["content"]["published_at"] <= end:
                # The first observed metrics win when pinned content repeats across pages.
                records.setdefault(r["platform_content_id"], r)
        ended = complete(body, frozen)
        next_cursor = body["max_cursor"]
        if not ended and (next_cursor in seen or (cursor and next_cursor >= cursor)):
            raise AdapterError("INVALID_RESPONSE")
        cursor = next_cursor
    if not ended:
        raise AdapterError("INVALID_RESPONSE")
    result = sorted(
        records.values(),
        key=lambda r: (
            r["content"]["like_count"] is None,
            -(r["content"]["like_count"] or 0),
            -r["content"]["published_at"].timestamp(),
            r["platform_content_id"],
        ),
    )
    return Batch("creator_works", result, len(records))
