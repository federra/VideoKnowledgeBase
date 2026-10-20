"""Single explicitly authorized series hot-list capture, no cookie or pagination."""

from app.connectors.redfox import AdapterError
from app.connectors.tikhub import TikHub

CAPABILITY = "douyin.series.hot"
VERSION = "tikhub-series-v1"
REQUEST = {"offset": 0, "count": 10, "content_type": 0}


class Series(TikHub):
    url = "https://api.tikhub.io/api/v1/douyin/web/fetch_series_aweme"

    def fetch(self, capability, request, *, maximum):
        if (
            capability != CAPABILITY
            or request != REQUEST
            or type(maximum) is not int
            or maximum != 10
            or any(type(v) is not int for v in request.values())
        ):
            raise AdapterError("INVALID_INPUT")
        return self._fetch(request)


def normalize_series(body, maximum=10):
    """Verified card_list[].series shape; counts belong to a series, not aweme_id."""
    from app.connectors.redfox import Batch, identifier, number, safe_url, text

    if (
        type(maximum) is not int
        or not 1 <= maximum <= 10
        or not isinstance(body, dict)
        or body.get("code") != 200
    ):
        raise AdapterError("INVALID_RESPONSE")
    data = body.get("data")
    if (
        not isinstance(data, dict)
        or data.get("status_code") != 0
        or not isinstance(data.get("card_list"), list)
        or len(data["card_list"]) > 100
    ):
        raise AdapterError("INVALID_RESPONSE")
    records = {}
    for card in data["card_list"]:
        if not isinstance(card, dict) or not isinstance(card.get("series"), dict):
            raise AdapterError("INVALID_RESPONSE")
        series = card["series"]
        ident = "series:" + identifier(series.get("series_id"))
        stats = series.get("stats") or {}
        author = series.get("author") or {}
        share = series.get("share_info") or {}
        if not all(isinstance(x, dict) for x in [stats, author, share]):
            raise AdapterError("INVALID_RESPONSE")
        uid = text(author.get("uid"))
        if uid == "0":
            uid = None
        record = {
            "platform_content_id": ident,
            "platform_uid": uid,
            "account_display_name": text(author.get("nickname")),
            "aliases": [],
            "display_name": text(series.get("series_name")),
            "content": {
                "description": text(series.get("desc")),
                "original_url": safe_url(share.get("share_url"), original=True),
                "cover_url": None,
                "duration_ms": None,
                "source_type_raw": "series",
                "published_at_raw": None,
                "published_at": None,
                "publish_timezone": None,
                "provider_updated_at_raw": None,
                "like_count": None,
                "comment_count": None,
                "share_count": None,
                "collect_count": number(stats.get("collect_vv")),
                "repost_count": None,
                "view_count": number(stats.get("play_vv")),
                "author_fans_count": None,
                "image_urls": None,
                "source_tags": [
                    {"kind": "series", "series_id": series["series_id"], "metric_scope": "series"}
                ],
            },
        }
        if ident in records and records[ident] != record:
            raise AdapterError("INVALID_RESPONSE")
        records.setdefault(ident, record)
    return Batch("board", list(records.values())[:maximum], len(data["card_list"]))
