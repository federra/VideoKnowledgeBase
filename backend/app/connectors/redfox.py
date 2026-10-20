"""Fixed RedFox capabilities. No pagination, redirects, hidden fallback or provider retries."""

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import httpx

KEYWORD_WORKS = "douyin.keyword.works"
KEYWORD_DEFAULT = "douyin.keyword.default"
DAILY_BOARD = "douyin.board.daily"


def item_limit(capability):
    return 10 if capability in (KEYWORD_WORKS, KEYWORD_DEFAULT, DAILY_BOARD) else 3


CAPABILITIES = {
    DAILY_BOARD: ("/story/api/dy/search/likesRank", "board", "board"),
    KEYWORD_WORKS: ("/story/api/dy/data/searchWork", "keyword", "keyword_works"),
    KEYWORD_DEFAULT: ("/story/api/dyData/searchArticle", "keyword", "keyword_works"),
    "douyin.account.search": ("/story/api/dyData/searchUser", "keyword", "account_discovery"),
    "douyin.creator.works": ("/story/api/dy/data/listWorkByAccount", "account", "creator_works"),
}
VERSION = "redfox-v1"
MAX_RESPONSE = 1024 * 1024


class AdapterError(ValueError):
    pass


@dataclass
class Batch:
    view_kind: str
    records: list[dict]
    returned_items: int


@dataclass
class Reply:
    http_status: int | None
    provider_code: str | None
    outcome: str
    raw_text: str
    captured_at: datetime
    batch: Batch | None = None
    error: str | None = None


def identifier(value):
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > 256
        or "[REDACTED]" in value
        or any(ord(c) < 32 for c in value)
    ):
        raise AdapterError("INVALID_RESPONSE")
    return value


def number(value):
    if value is None or value == "":
        return None
    if type(value) is int:
        n = value
    elif (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= 19
        and (value == "0" or not value.startswith("0"))
    ):
        n = int(value)
    else:
        raise AdapterError("INVALID_RESPONSE")
    if not 0 <= n <= 9223372036854775807:
        raise AdapterError("INVALID_RESPONSE")
    return n


def text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterError("INVALID_RESPONSE")
    return value if value.strip() else None


def safe_url(value, *, original=False):
    value = text(value)
    if value is None:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.port not in (None, 443)
            or not host
            or any(ord(c) <= 32 for c in value)
        ):
            return None
        if original:
            if not any(
                host == d or host.endswith("." + d) for d in ["douyin.com", "iesdouyin.com"]
            ):
                return None
        elif not any(
            host == d or host.endswith("." + d)
            for d in ["douyinpic.com", "byteimg.com", "douyincdn.com", "douyin.com"]
        ):
            return None
    except ValueError:
        return None
    return value


def normalize(capability, payload, *, maximum=1, target=None):
    if capability not in CAPABILITIES:
        raise AdapterError("UNSUPPORTED_SOURCE")
    if type(maximum) is not int or not 1 <= maximum <= item_limit(capability):
        raise AdapterError("INVALID_RESPONSE")
    if not isinstance(payload, dict) or type(payload.get("code")) is not int:
        raise AdapterError("INVALID_RESPONSE")
    if payload["code"] != 2000:
        raise AdapterError("SOURCE_UNAVAILABLE")
    data = payload.get("data")
    rows = (
        data if capability == DAILY_BOARD else data.get("list") if isinstance(data, dict) else None
    )
    if not isinstance(rows, list) or len(rows) > 500:
        raise AdapterError("INVALID_RESPONSE")
    records = {}
    for row in rows:
        if not isinstance(row, dict):
            raise AdapterError("INVALID_RESPONSE")
        if capability in (KEYWORD_DEFAULT, DAILY_BOARD):
            # Quality library uses workId and seconds, not broad-library videoId/milliseconds.
            identity = identifier(row.get("workId"))
            description = text(row.get("content"))
            if capability == KEYWORD_DEFAULT:
                if row.get("workType") != "视频" or "漫剧" not in (description or ""):
                    continue
            elif row.get("category") != "小剧场" or str(row.get("workType")) not in ("视频", "0"):
                continue
            seconds = number(row.get("duration")) if capability == KEYWORD_DEFAULT else None
            if seconds is not None and seconds > 9223372036854775:
                raise AdapterError("INVALID_RESPONSE")
            record = {
                "platform_content_id": identity,
                "platform_uid": None,
                "account_display_name": text(row.get("accountName")),
                "aliases": [],
                "content": {
                    "description": description,
                    "original_url": safe_url(row.get("workUrl"), original=True),
                    "cover_url": safe_url(row.get("coverUrl")),
                    "duration_ms": seconds * 1000 if seconds is not None else None,
                    "source_type_raw": str(row.get("workType"))
                    if capability == DAILY_BOARD
                    else text(row.get("workType")),
                    "published_at_raw": text(row.get("publishTime")),
                    "published_at": None,
                    "publish_timezone": None,
                    "provider_updated_at_raw": text(row.get("crawlTime")),
                    "like_count": number(row.get("likeCount")),
                    "comment_count": number(row.get("commentCount")),
                    "share_count": number(row.get("shareCount")),
                    "collect_count": number(row.get("collectCount")),
                    "repost_count": number(row.get("repostCount")),
                    "view_count": None,
                    "author_fans_count": number(row.get("followerCount")),
                    "image_urls": None,
                    "source_tags": None,
                },
            }
        elif capability == "douyin.account.search":
            uid = identifier(row.get("uid"))
            alias = text(row.get("accountId"))
            record = {
                "platform_uid": uid,
                "account_display_name": text(row.get("nickname")),
                "aliases": [("unique_name", alias)] if alias else [],
                "account": {
                    "nickname": text(row.get("nickname")),
                    "unique_name": alias,
                    "avatar_url": safe_url(row.get("avatarUrl")),
                    "follower_count": number(row.get("followerCount")),
                    "work_count": number(row.get("awemeCount")),
                    "total_liked_count": number(row.get("totalFavorited")),
                    "provider_updated_at_raw": text(row.get("crawlTime")),
                },
            }
            identity = uid
        else:
            identity = identifier(row.get("videoId"))
            uid = identifier(row["authorUid"]) if row.get("authorUid") is not None else None
            if target is not None and uid is not None and uid != target:
                raise AdapterError("INVALID_RESPONSE")
            images = row.get("imageUrlList")
            tags = row.get("tagList")
            if images is not None and (
                not isinstance(images, list) or not all(isinstance(v, str) for v in images)
            ):
                raise AdapterError("INVALID_RESPONSE")
            if tags is not None and (
                not isinstance(tags, list) or not all(isinstance(v, dict) for v in tags)
            ):
                raise AdapterError("INVALID_RESPONSE")
            aliases = []
            for field, kind in [
                ("authorUniqueId", "unique_name"),
                ("authorShortId", "short_id"),
                ("authorSecUid", "sec_uid"),
            ]:
                value = text(row.get(field))
                if value and value != "0":
                    aliases.append((kind, value))
            record = {
                "platform_content_id": identity,
                "platform_uid": uid,
                "account_display_name": text(row.get("authorName")),
                "aliases": aliases if uid else [],
                "content": {
                    "description": text(row.get("content")),
                    "original_url": safe_url(row.get("opusUrl"), original=True),
                    "cover_url": safe_url(row.get("coverUrl")),
                    "duration_ms": number(row.get("duration")),
                    "source_type_raw": text(row.get("videoType")),
                    "published_at_raw": text(row.get("publishTime")),
                    "published_at": None,
                    "publish_timezone": None,
                    "provider_updated_at_raw": text(row.get("crawlTime")),
                    "like_count": number(row.get("likeCount")),
                    "comment_count": number(row.get("commentCount")),
                    "share_count": number(row.get("shareCount")),
                    "collect_count": number(row.get("collectCount")),
                    "repost_count": number(row.get("repostCount")),
                    "view_count": number(row.get("viewCount")),
                    "author_fans_count": number(row.get("authorFansCount")),
                    "image_urls": [u for v in images if (u := safe_url(v))]
                    if images is not None
                    else None,
                    "source_tags": tags,
                },
            }
        if identity in records and records[identity] != record:
            raise AdapterError("INVALID_RESPONSE")
        records[identity] = record
    return Batch(CAPABILITIES[capability][2], list(records.values())[:maximum], len(rows))


def safe_evidence(raw, key, *, truncated=False):
    raw = raw.replace(key.encode(), b"[REDACTED]")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return json.dumps(
            {"encoding": "base64", "truncated": truncated, "body": base64.b64encode(raw).decode()}
        )
    if truncated:
        return json.dumps({"truncated": True, "body_prefix": decoded})
    return decoded if decoded.strip() else '{"empty_response":true}'


class RedFox:
    def __init__(self, key_provider, *, transport=None):
        self.key_provider, self.transport = key_provider, transport

    def ready(self):
        key = self.key_provider()
        if not isinstance(key, str) or not key or any(ord(c) < 33 for c in key):
            raise AdapterError("SOURCE_UNAVAILABLE")
        return key

    def fetch(self, capability, request, *, maximum=None):
        if capability not in CAPABILITIES:
            raise AdapterError("UNSUPPORTED_SOURCE")
        if capability == DAILY_BOARD:
            if (
                set(request) != {"type", "startTime", "endTime"}
                or request["type"] != "小剧场"
                or request["startTime"] != request["endTime"]
                or type(maximum) is not int
                or not 1 <= maximum <= 10
            ):
                raise AdapterError("UNSUPPORTED_SOURCE")
            try:
                parsed = date.fromisoformat(request["startTime"])
                if parsed.isoformat() != request["startTime"]:
                    raise ValueError()
            except (TypeError, ValueError):
                raise AdapterError("UNSUPPORTED_SOURCE") from None
        elif capability == KEYWORD_DEFAULT:
            if (
                request != {"keyword": "漫剧", "offset": 0, "sortType": "_0"}
                or type(request.get("offset")) is not int
                or type(maximum) is not int
                or not 1 <= maximum <= 10
            ):
                raise AdapterError("UNSUPPORTED_SOURCE")
        elif capability == KEYWORD_WORKS:
            if (
                set(request) != {"keyword", "exactMatch", "pageNum", "pageSize"}
                or request["keyword"] != "漫剧"
                or request["exactMatch"] is not True
                or request["pageNum"] != 1
                or type(request["pageSize"]) is not int
                or not 1 <= request["pageSize"] <= 10
                or maximum != request["pageSize"]
            ):
                raise AdapterError("UNSUPPORTED_SOURCE")
        elif capability == "douyin.creator.works":
            if (
                set(request) != {"userId", "pageNum", "pageSize"}
                or request["pageNum"] != 1
                or type(request["pageSize"]) is not int
                or not 1 <= request["pageSize"] <= 3
            ):
                raise AdapterError("UNSUPPORTED_SOURCE")
            identifier(request["userId"])
        elif (
            set(request) != {"keyword", "offset", "sortType"}
            or request["offset"] != 0
            or request["sortType"] != "_0"
            or not text(request["keyword"])
        ):
            raise AdapterError("UNSUPPORTED_SOURCE")
        key = self.ready()
        return asyncio.run(
            self._fetch(capability, request, key, maximum or request.get("pageSize", 3))
        )

    async def _fetch(self, capability, request, key, maximum):
        status = None
        raw = bytearray()
        try:
            async with (
                asyncio.timeout(20),
                httpx.AsyncClient(
                    timeout=httpx.Timeout(5),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client,
                client.stream(
                    "POST",
                    "https://redfox.hk" + CAPABILITIES[capability][0],
                    headers={"REDFOX_API_KEY": key, "Accept-Encoding": "identity"},
                    json=request,
                ) as response,
            ):
                status = response.status_code
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    return Reply(
                        status,
                        None,
                        "invalid_shape",
                        '{"unsupported_encoding":true}',
                        datetime.now(UTC),
                        error="INVALID_RESPONSE",
                    )
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > MAX_RESPONSE:
                        raw.extend(chunk[: MAX_RESPONSE - len(raw)])
                        return Reply(
                            status,
                            None,
                            "invalid_shape",
                            safe_evidence(bytes(raw), key, truncated=True),
                            datetime.now(UTC),
                            error="INVALID_RESPONSE",
                        )
                    raw.extend(chunk)
        except (httpx.HTTPError, TimeoutError):
            return Reply(
                status,
                None,
                "network_error",
                safe_evidence(bytes(raw), key, truncated=True),
                datetime.now(UTC),
                error="EXTERNAL_RESULT_UNKNOWN",
            )
        now = datetime.now(UTC)
        evidence = safe_evidence(bytes(raw), key)
        try:
            payload = json.loads(evidence)
        except (ValueError, UnicodeError):
            payload = None
        code = (
            str(payload["code"])
            if isinstance(payload, dict)
            and type(payload.get("code")) is int
            and len(str(payload["code"])) <= 20
            else None
        )
        if not 200 <= status < 300:
            error = (
                "RATE_LIMITED"
                if status == 429
                else "SOURCE_UNAVAILABLE"
                if status in (301, 302, 303, 307, 308, 404, 410)
                else "FETCH_FAILED"
            )
            return Reply(status, code, "http_error", evidence, now, error=error)
        try:
            batch = normalize(capability, payload, maximum=maximum, target=request.get("userId"))
        except AdapterError as exc:
            return Reply(
                status,
                code,
                "provider_error" if str(exc) == "SOURCE_UNAVAILABLE" else "invalid_shape",
                evidence,
                now,
                error=str(exc),
            )
        return Reply(status, code, "success", evidence, now, batch=batch)


def evidence_sha(reply):
    return hashlib.sha256(reply.raw_text.encode()).hexdigest()
