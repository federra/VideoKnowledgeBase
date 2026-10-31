"""Verified public short-drama JSON. Independent implementation; no paid fallback."""

from datetime import UTC, datetime

from app.connectors.redfox import AdapterError, Batch, number, text

VERSION = "douyin-public-series-v1"
CAPABILITY = "douyin.creator.series"
POLICY = "complete-directory-top10-first-episode15-v1"
MAX_PAGES = 60
MAX_CALLS = MAX_PAGES + 20


def checked(body):
    if (
        not isinstance(body, dict)
        or type(body.get("status_code")) is not int
        or body["status_code"] != 0
    ):
        raise AdapterError("INVALID_RESPONSE")
    return body


def catalog(body, sec, uid=None):
    checked(body)
    rows = body.get("series_infos")
    if rows is None and "series_infos" in body:
        rows = []
    if not isinstance(rows, list) or len(rows) > 100:
        raise AdapterError("INVALID_RESPONSE")
    for s in rows:
        a = s.get("author") or {}
        if a.get("sec_uid") != sec or (uid is not None and a.get("uid") != uid):
            raise AdapterError("INVALID_RESPONSE")
    if (
        type(body.get("has_more")) is not int
        or body["has_more"] not in (0, 1)
        or type(body.get("cursor")) is not int
        or body["cursor"] < 0
    ):
        raise AdapterError("INVALID_RESPONSE")
    return rows


def catalog_identity(body, sec):
    rows = catalog(body, sec)
    identities = {s["author"].get("uid") for s in rows}
    if len(identities) != 1 or not rows:
        raise AdapterError("INVALID_RESPONSE")
    uid = identities.pop()
    if (
        not isinstance(uid, str)
        or not uid.isascii()
        or not uid.isdecimal()
        or not 3 <= len(uid) <= 25
        or uid.startswith("0")
    ):
        raise AdapterError("INVALID_RESPONSE")
    return {"uid": uid, "sec_uid": sec, "name": text(rows[0]["author"].get("nickname")) or ""}


def normalize_page(body, sec, uid):
    records = []
    for s in catalog(body, sec, uid):
        sid = s.get("series_id")
        if not isinstance(sid, str) or not sid.isascii() or not sid.isdecimal():
            raise AdapterError("INVALID_RESPONSE")
        stats = s.get("stats") or {}
        tags = [
            v["name"]
            for v in s.get("series_content_types_new") or s.get("series_content_types") or []
            if isinstance(v, dict) and isinstance(v.get("name"), str)
        ]
        records.append(
            {
                "platform_content_id": "series:" + sid,
                "platform_uid": uid,
                "account_display_name": text(s["author"].get("nickname")),
                "display_name": text(s.get("series_name")),
                "aliases": [("sec_uid", sec)],
                "genre_tags": tags,
                "content": {
                    "description": text(s.get("desc")),
                    "original_url": f"https://www.douyin.com/collection/{sid}/1",
                    "source_type_raw": "series",
                    "view_count": number(stats.get("play_vv")),
                    "collect_count": number(stats.get("collect_vv")),
                    "like_count": None,
                    "comment_count": None,
                    "share_count": None,
                    "repost_count": None,
                    "source_tags": [
                        {"kind": POLICY, "series_id": sid, "metric_scope": "series", "genres": tags}
                    ],
                },
            }
        )
    return Batch("creator_works", records, len(records))


def top(pages, sec, uid):
    cursor, seen, records = 0, set(), {}
    if not pages or len(pages) > MAX_PAGES:
        raise AdapterError("INVALID_RESPONSE")
    ended = False
    for requested, body in pages:
        if ended or requested != cursor or cursor in seen:
            raise AdapterError("INVALID_RESPONSE")
        seen.add(cursor)
        for r in normalize_page(body, sec, uid).records:
            if r["content"]["view_count"] is None:
                raise AdapterError("INVALID_RESPONSE")
            ident = r["platform_content_id"]
            if ident in records and records[ident] != r:
                raise AdapterError("INVALID_RESPONSE")
            records[ident] = r
        ended = body["has_more"] == 0
        cursor = body["cursor"]
    if not ended:
        raise AdapterError("INVALID_RESPONSE")
    result = sorted(
        records.values(), key=lambda r: (-r["content"]["view_count"], r["platform_content_id"])
    )[:10]
    return Batch("creator_works", result, len(records))


def first_episode(body, sid, uid):
    checked(body)
    rows = body.get("aweme_list")
    if not isinstance(rows, list) or len(rows) > 100:
        raise AdapterError("INVALID_RESPONSE")
    first = []
    for a in rows:
        if (a.get("series_info") or a.get("series_basic_info") or {}).get("series_id") != sid or (
            a.get("author") or {}
        ).get("uid") != uid:
            raise AdapterError("INVALID_RESPONSE")
        if (a.get("series_play_info") or {}).get("series_aweme_index") == 1:
            first.append(a.get("aweme_id"))
    if (
        len(first) != 1
        or not isinstance(first[0], str)
        or not first[0].isascii()
        or not first[0].isdecimal()
    ):
        raise AdapterError("INVALID_RESPONSE")
    return first[0]


def comments(body, aweme):
    checked(body)
    rows = body.get("comments")
    if rows is None and body.get("total") == 0:
        rows = []
    if not isinstance(rows, list) or len(rows) > 100:
        raise AdapterError("INVALID_RESPONSE")
    result, seen = [], set()
    for c in rows[:15]:
        cid, value = c.get("cid"), text(c.get("text"))
        if (
            c.get("aweme_id") != aweme
            or not isinstance(cid, str)
            or not cid.isascii()
            or not cid.isdecimal()
        ):
            raise AdapterError("INVALID_RESPONSE")
        if not value or cid in seen:
            continue
        seen.add(cid)
        epoch = number(c.get("create_time"))
        try:
            posted = datetime.fromtimestamp(epoch, UTC) if epoch is not None else None
        except (OverflowError, OSError, ValueError):
            raise AdapterError("INVALID_RESPONSE") from None
        result.append(
            {
                "platform_comment_id": cid,
                "body_text": value,
                "username": text((c.get("user") or {}).get("nickname")),
                "like_count": number(c.get("digg_count")),
                "posted_at_raw": str(epoch) if epoch is not None else None,
                "posted_at": posted,
                "posted_timezone": "UTC" if posted else None,
                "sample_position": len(result),
            }
        )
    return result
