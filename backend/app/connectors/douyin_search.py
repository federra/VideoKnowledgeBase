"""Fixed microfilm comprehensive video search. Provider order is never likes order."""

import json

from app.connectors import douyin_posts as posts
from app.connectors.douyin_series import checked, comments
from app.connectors.redfox import AdapterError, Batch

CAPABILITY = "douyin.search.microfilm"
VERSION = "douyin-microfilm-search-v1"
POLICY = "microfilm-comprehensive-v1"
KIND = "collect.microfilm"
MAX_ITEMS = 50
MAX_PAGES = 10
MAX_CALLS = 112
REQUEST = {
    "keyword": "微电影",
    "search_channel": "aweme_video_web",
    "sort_type": 0,
    "maximum": 50,
    "comments_per_video": 15,
    "search_max_pages": 10,
    "request_unit": "page_visit_or_xhr",
}
PATHS = ("/aweme/v1/web/general/search/single/", "/aweme/v1/web/search/item/")


def search_page(value):
    if not isinstance(value, dict) or value.get("kind") != "search":
        raise AdapterError("INVALID_RESPONSE")
    p = value.get("parameters") or {}
    if not isinstance(p, dict):
        raise AdapterError("INVALID_RESPONSE")
    sort = p.get("sort_type", "0")
    if sort != "0":
        raise AdapterError("INVALID_RESPONSE")
    if p.get("filter_selected"):
        try:
            sort = str(json.loads(p["filter_selected"]).get("sort_type", "0"))
        except (ValueError, TypeError):
            raise AdapterError("INVALID_RESPONSE") from None
    if p.get("keyword") != "微电影" or p.get("search_channel") != "aweme_video_web" or sort != "0":
        raise AdapterError("INVALID_RESPONSE")
    b = checked(value["body"])
    data = b.get("data")
    if (
        not isinstance(data, list)
        or len(data) > 50
        or type(b.get("has_more")) is not int
        or b["has_more"] not in (0, 1)
        or type(b.get("cursor")) is not int
        or b["cursor"] < 0
    ):
        raise AdapterError("INVALID_RESPONSE")
    try:
        offset = int(p["offset"])
    except (ValueError, TypeError, KeyError):
        raise AdapterError("INVALID_RESPONSE") from None
    records = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise AdapterError("INVALID_RESPONSE")
        a = item.get("aweme_info")
        if a is not None and not isinstance(a, dict):
            raise AdapterError("INVALID_RESPONSE")
        if not a or item.get("is_ad") or a.get("is_ads"):
            continue
        author = a.get("author") or {}
        if not isinstance(author, dict):
            raise AdapterError("INVALID_RESPONSE")
        uid, sec = author.get("uid"), author.get("sec_uid")
        if not isinstance(uid, str) or not isinstance(sec, str) or not uid or not sec:
            raise AdapterError("INVALID_RESPONSE")
        batch = posts.normalize_page(
            {"status_code": 0, "has_more": 0, "max_cursor": 0, "aweme_list": [a]}, sec, uid
        )
        for r in batch.records:
            r["aliases"] = []  # Search never replaces verified monitored-profile identity evidence.
            r["provider_rank"] = offset + index + 1
            r["content"]["source_type_raw"] = "keyword-video-search"
            r["content"]["source_tags"] = [
                {
                    "kind": POLICY,
                    "keyword": "微电影",
                    "order": "provider_comprehensive",
                    "provider_position": offset + index + 1,
                }
            ]
            records.append(r)
    return Batch("board", records, len(data))


def combine(pages):
    if not pages or len(pages) > MAX_PAGES:
        raise AdapterError("INVALID_RESPONSE")
    cursor, seen, records, ended = 0, set(), {}, False
    search_id = ""
    for value in pages:
        if ended:
            raise AdapterError("INVALID_RESPONSE")
        p = value["parameters"]
        if p.get("search_id", "") != search_id:
            raise AdapterError("INVALID_RESPONSE")
        offset = int(p.get("offset", -1))
        if offset != cursor or cursor in seen:
            raise AdapterError("INVALID_RESPONSE")
        seen.add(cursor)
        batch = search_page(value)
        for r in batch.records:
            records.setdefault(r["platform_content_id"], r)
        b = value["body"]
        ended = b["has_more"] == 0 or len(records) >= MAX_ITEMS
        cursor = b["cursor"]
        search_id = (b.get("extra") or {}).get("logid", "")
        if not ended and (not isinstance(search_id, str) or not search_id):
            raise AdapterError("INVALID_RESPONSE")
        if not ended and (cursor <= offset or cursor in seen):
            raise AdapterError("INVALID_RESPONSE")
    return Batch("board", list(records.values())[:MAX_ITEMS], len(records)), ended


def comment_page(value, aid):
    if value.get("kind") != "comments" or value.get("parameters", {}).get("aweme_id") != aid:
        raise AdapterError("INVALID_RESPONSE")
    return comments(value["body"], aid)
