"""Fixed public Hongguo pages. JSON is decoded, never executed; no media or paging."""

import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from app.connectors.novel_metrics import reader_number
from app.connectors.qidian_desktop import Document
from app.connectors.redfox import AdapterError, Batch, Reply, number

VERSION = "hongguo-public-v1"
HOST = "https://hongguoduanju.com"
BOARDS = {
    "hot-drama": "红果热播榜",
    "hot-real-drama": "真人剧热播榜",
    "hot-ai-drama": "AI剧热播榜",
    "hot-comic-drama": "漫剧热播榜",
}
INTERVAL = 10


def encode_html(html, *, capture=None):
    """PostgreSQL TEXT rejects NUL; JSON escapes it without deleting source bytes."""
    value = {
        "format": "hongguo-html-json-v1",
        "response_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "html": html,
    }
    if capture is not None:
        value["capture"] = capture
    return json.dumps(value, ensure_ascii=False)


def response_html(value):
    if value.startswith('{"format":'):
        data = json.loads(value)
        if data.get("format") == "hongguo-saved-http-v1":
            try:
                if set(data) != {"format", "response_sha256", "html_base64", "capture"}:
                    raise ValueError
                body = base64.b64decode(data["html_base64"], validate=True)
                if (
                    not body
                    or len(body) > 4 * 1024 * 1024
                    or base64.b64encode(body).decode("ascii") != data["html_base64"]
                    or hashlib.sha256(body).hexdigest() != data["response_sha256"]
                ):
                    raise ValueError
                return body.decode("utf-8")
            except (ValueError, TypeError, UnicodeError, binascii.Error):
                raise AdapterError("INVALID_RESPONSE") from None
        if (
            data.get("format") != "hongguo-html-json-v1"
            or hashlib.sha256(data["html"].encode()).hexdigest() != data["response_sha256"]
        ):
            raise AdapterError("INVALID_RESPONSE")
        return data["html"]
    return value


def one(values):
    if len(values) != 1:
        raise AdapterError("INVALID_RESPONSE")
    return values[0]


def prefixed(node, tag, prefix):
    return [
        n
        for n in node.all(tag=tag)
        if any(c.startswith(prefix) for c in n.attrs.get("class", "").split())
    ]


def split_tags(tags):
    words = [s.strip() for tag in tags for s in re.split(r"[.·・。|｜]", tag) if s.strip()]
    return (words[0] if words else None, words[1] if len(words) > 1 else None)


def normalize_board(html, board):
    try:
        name = BOARDS[board]
        root = Document(response_html(html).replace("\x00", "")).root
        if one(root.all(tag="h1")).text() != name:
            raise AdapterError("INVALID_RESPONSE")
        canonical = one([n for n in root.all(tag="link") if n.attrs.get("rel") == "canonical"])
        if canonical.attrs.get("href") != HOST + "/rank/" + board:
            raise AdapterError("INVALID_RESPONSE")
        listing = one([n for n in root.all(tag="ol") if n.attrs.get("aria-label") == name])
        cards = listing.all(tag="article")
        if not cards or len(cards) > 100:
            raise AdapterError("INVALID_RESPONSE")
        records, seen = [], set()
        for position, card in enumerate(cards[:20], 1):
            title = one(card.all(tag="h2"))
            match = re.fullmatch(r"rank-title-([0-9]{1,32})", title.attrs.get("id", ""))
            if not match or card.attrs.get("aria-labelledby") != title.attrs["id"]:
                raise AdapterError("INVALID_RESPONSE")
            ident = match[1]
            detail = urlsplit(
                urljoin(
                    HOST,
                    one([n for n in card.all(tag="a") if n.all(tag="h2")]).attrs.get("href", ""),
                )
            )
            if (
                detail.scheme != "https"
                or detail.netloc != "hongguoduanju.com"
                or detail.path != "/detail"
                or parse_qs(detail.query) != {"series_id": [ident]}
                or ident in seen
                or not title.text().strip()
            ):
                raise AdapterError("INVALID_RESPONSE")
            seen.add(ident)
            rank = int(one(prefixed(card, "span", "pc-badge-number-")).text())
            if rank != position:
                raise AdapterError("INVALID_RESPONSE")
            heat = one(prefixed(card, "p", "pc-metrics-")).text()
            if not heat.endswith("热度"):
                raise AdapterError("INVALID_RESPONSE")
            heat_value = reader_number(heat.removesuffix("热度"))
            items = [
                n.text()
                for n in one(
                    [n for n in card.all(tag="ul") if n.attrs.get("aria-label") == "作品互动数据"]
                ).all(tag="li")
            ]
            like = one([v for v in items if v.endswith("点赞")])
            collect = one([v for v in items if v.endswith("收藏")])
            scores = [v for v in items if v.startswith("评分")]
            score = one(scores) if scores else None
            if score is not None and not re.fullmatch(
                r"评分(?:[0-9](?:\.[0-9])?|10(?:\.0)?)", score
            ):
                raise AdapterError("INVALID_RESPONSE")
            tags = [n.text() for n in one(prefixed(card, "p", "pc-categories-")).all(tag="span")]
            genre, subgenre = split_tags(tags)
            genre_tags = [genre] if genre else []
            hierarchy = (
                [{"genre": genre, "subgenres": [subgenre] if subgenre else []}] if genre else []
            )
            meta = {
                "kind": VERSION,
                "title": title.text(),
                "board": board,
                "tags_raw": tags,
                "heat_raw": heat,
                "heat_value": heat_value,
                "score_raw": score,
                "like_raw": like,
                "collect_raw": collect,
                "metric_precision": "website_display_rounded",
            }
            records.append(
                {
                    "platform_content_id": ident,
                    "platform_uid": None,
                    "account_display_name": None,
                    "aliases": [],
                    "provider_rank": rank,
                    "display_name": title.text(),
                    "genre_tags": genre_tags,
                    "genre_hierarchy": hierarchy,
                    "heat_display": heat,
                    "heat_value": heat_value,
                    "score_display": score.removeprefix("评分") if score else None,
                    "content": {
                        "description": one(prefixed(card, "p", "pc-description-")).text(),
                        "original_url": detail.geturl(),
                        "source_type_raw": "series",
                        "view_count": None,
                        "comment_count": None,
                        "share_count": None,
                        "like_count": reader_number(like.removesuffix("点赞")),
                        "collect_count": reader_number(collect.removesuffix("收藏")),
                        "source_tags": [meta],
                    },
                }
            )
        return Batch("board", records, len(cards))
    except (KeyError, TypeError, ValueError, IndexError):
        raise AdapterError("INVALID_RESPONSE") from None


def parse_comments(html, series):
    try:
        scripts = [
            "".join(x for x in s.children if isinstance(x, str))
            for s in Document(response_html(html).replace("\x00", "")).root.all(tag="script")
        ]
        candidates = [
            m[1] for s in scripts if (m := re.match(r"\s*_ROUTER_DATA\s*=\s*(.*)", s, re.DOTALL))
        ]
        data, _ = json.JSONDecoder().raw_decode(one(candidates))
        page = data["loaderData"]["player_(series_id)/page"]
        detail, episode = page["seriesDetail"], page["vid"]
        if (
            page.get("series_id") != series
            or page.get("isSuccess") is not True
            or detail["series_id"] != series
            or not re.fullmatch(r"[0-9]{1,32}", episode)
            or detail["vid_list"].count(episode) != 1
        ):
            raise AdapterError("INVALID_RESPONSE")
        block = page["episodeSocialInfo"]["reviews"]
        rows, total = block["reviews"], number(block.get("total_count"))
        if not isinstance(rows, list) or len(rows) > 100:
            raise AdapterError("INVALID_RESPONSE")
        comments = []
        for pos, row in enumerate(rows[:15]):
            body, name, epoch = row.get("content"), row.get("user_name"), row.get("create_time")
            if (
                not isinstance(body, str)
                or not body.strip()
                or not isinstance(name, str)
                or not isinstance(epoch, str)
                or not re.fullmatch(r"[0-9]{1,12}", epoch)
            ):
                raise AdapterError("INVALID_RESPONSE")
            comments.append(
                {
                    "platform_comment_id": None,
                    "body_text": body.replace("\x00", "\ufffd"),
                    "username": name.replace("\x00", "\ufffd") or None,
                    "like_count": number(row.get("digg_count")),
                    "posted_at_raw": epoch,
                    "posted_at": datetime.fromtimestamp(int(epoch), UTC),
                    "posted_timezone": "UTC",
                    "sample_position": pos,
                }
            )
        return {
            "comments": comments,
            "total_count_reported": total,
            "page_episode_id": episode,
            "page_episode_number": detail["vid_list"].index(episode) + 1,
            "comment_scope": "player_preload_context",
            "cross_episode_pool_verified": False,
        }
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, OSError):
        raise AdapterError("INVALID_RESPONSE") from None


class Hongguo:
    def __init__(self, client=None, throttle_path=None):
        self.client = client
        self.throttle_path = Path(
            throttle_path or Path(__file__).resolve().parents[3] / "data/hongguo/request-gate.json"
        )

    def ready(self):
        # Check before Collect reserves an external-call budget. A known cooldown
        # must not create a spurious "external result unknown" reservation.
        if self.throttle_path.exists():
            with self.throttle_path.open() as gate:
                fcntl.flock(gate, fcntl.LOCK_SH)
                state = json.loads(gate.read() or "{}")
                if state.get("blocked_until", 0) > time.time():
                    raise AdapterError("SOURCE_UNAVAILABLE")

    def fetch(self, capability, request, *, maximum):
        if (
            capability == "hongguo.board"
            and request == {"board": request.get("board")}
            and request.get("board") in BOARDS
            and type(maximum) is int
            and maximum == 20
        ):
            url = HOST + "/rank/" + request["board"]
        elif (
            capability == "hongguo.comments"
            and request == {"series_id": request.get("series_id")}
            and re.fullmatch(r"[0-9]{1,32}", str(request.get("series_id", "")))
            and isinstance(request["series_id"], str)
            and type(maximum) is int
            and maximum == 15
        ):
            url = HOST + "/player/" + request["series_id"]
        else:
            raise AdapterError("INVALID_INPUT")
        self.throttle_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.throttle_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+") as gate:
            fcntl.flock(gate, fcntl.LOCK_EX)
            state = json.loads(gate.read() or "{}")
            if state.get("blocked_until", 0) > time.time():
                raise AdapterError("SOURCE_UNAVAILABLE")
            time.sleep(max(0, INTERVAL - (time.time() - state.get("last_request", 0))))
            state["last_request"] = time.time()

            def save():
                gate.seek(0)
                json.dump(state, gate)
                gate.truncate()
                gate.flush()
                os.fsync(gate.fileno())

            save()  # Persist intent before I/O, including timeouts.
            owned = self.client is None
            client = self.client or httpx.Client(timeout=25, follow_redirects=False)
            status, raw, batch, error, outcome = None, "", None, None, "network_error"
            body, received = bytearray(), 0
            stage, failure, exception_type = "receive", None, None
            complete, decoded = False, False
            content_type, content_encoding, content_length = None, None, None
            response = None
            try:
                with client.stream(
                    "GET",
                    url,
                    headers={
                        "Accept": "text/html",
                        # Fixed small HTML pages need no content compression. This
                        # also keeps received bytes directly observable on timeout.
                        "Accept-Encoding": "identity",
                        "User-Agent": "ContentIntelligenceResearch/1.0",
                    },
                    follow_redirects=False,
                ) as response:
                    status = response.status_code
                    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    content_type = (
                        mime
                        if mime
                        in {
                            "text/html",
                            "application/xhtml+xml",
                            "application/json",
                            "text/plain",
                            "application/octet-stream",
                        }
                        else "other"
                    )
                    encoding = response.headers.get("content-encoding", "identity").lower()
                    content_encoding = (
                        encoding
                        if encoding
                        in {
                            "identity",
                            "gzip",
                            "br",
                            "deflate",
                            "zstd",
                        }
                        else "other"
                    )
                    length = response.headers.get("content-length", "")
                    if re.fullmatch(r"[0-9]{1,20}", length):
                        content_length = int(length)
                    for chunk in response.iter_bytes():
                        received += len(chunk)
                        remaining = 4 * 1024 * 1024 - len(body)
                        body.extend(chunk[:remaining])
                        if received > 4 * 1024 * 1024:
                            failure = "body_too_large"
                            raise AdapterError("INVALID_RESPONSE")
                    complete = True
                    if not body and status == 200:
                        failure = "empty_body"
                        raise AdapterError("INVALID_RESPONSE")
                    stage = "decode"
                    raw = bytes(body).decode("utf-8")
                    decoded = True
                if status != 200:
                    stage, failure = "http", "http_status"
                    error, outcome = "SOURCE_UNAVAILABLE", "http_error"
                elif capability == "hongguo.board":
                    stage = "parse"
                    batch = normalize_board(raw, request["board"])
                    outcome = "success"
                else:
                    stage = "parse"
                    parse_comments(raw, request["series_id"])
                    outcome = "success"
            except (httpx.HTTPError, UnicodeError, AdapterError) as exc:
                # Only an exception class is safe: messages can include request details.
                exception_type = type(exc).__name__
                if isinstance(exc, httpx.DecodingError):
                    stage, failure = "decode", "content_decode_error"
                failure = failure or (
                    "transfer_error"
                    if isinstance(exc, httpx.HTTPError)
                    else "invalid_utf8"
                    if isinstance(exc, UnicodeError)
                    else "invalid_shape"
                )
                transport_failure = isinstance(exc, httpx.HTTPError) and not isinstance(exc, httpx.DecodingError)
                error = "SOURCE_UNAVAILABLE" if transport_failure or status != 200 else "INVALID_RESPONSE"
                outcome = "network_error" if transport_failure or status != 200 else "invalid_shape"
            finally:
                # A diagnostic write failure must not undo an already known stop.
                if error:
                    state["blocked_until"] = time.time() + 24 * 3600
                    state["blocked_reason"] = error
                    state["blocked_http_status"] = status
                    save()
                if owned:
                    client.close()
                # Save bounded bytes even when reception or UTF-8 decoding failed.
                # Partial bytes are evidence only; never publish them as a full HTML page.
                capture = {
                    "url": url,
                    "http_status": status,
                    "captured_at": datetime.now(UTC).isoformat(),
                    "requested_at": datetime.fromtimestamp(state["last_request"], UTC).isoformat(),
                    "sha256": hashlib.sha256(raw.encode()).hexdigest() if decoded else None,
                    "collection_job_id": getattr(self, "capture_job_id", None),
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "body_representation": "httpx_decoded_bytes",
                    "saved_bytes": len(body),
                    "received_bytes": received,
                    # iter_bytes() counts decoded output only: gzip may consume
                    # a prefix and then stall before yielding any decoded bytes.
                    "received_wire_bytes": response.num_bytes_downloaded if response else 0,
                    "body_complete": complete,
                    "text_available": decoded,
                    "failure_stage": stage if error else None,
                    "failure_kind": failure,
                    "exception_type": exception_type,
                    "content_type": content_type,
                    "content_encoding": content_encoding,
                    "content_length": content_length,
                }
                stem = (
                    ("board-" + request["board"])
                    if capability == "hongguo.board"
                    else ("player-" + request["series_id"])
                )
                stem += "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                files = [(".body", bytes(body)), (".json", json.dumps(capture).encode())]
                if decoded:
                    files.append((".html", raw.encode()))
                for suffix, content in files:
                    capture_fd = os.open(
                        self.throttle_path.parent / (stem + suffix),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                    with os.fdopen(capture_fd, "wb") as output:
                        output.write(content)
            return Reply(
                status,
                None,
                outcome,
                # Keep complete text envelopes byte-compatible with strict offline
                # recovery. Their diagnostics are in the durable sidecar instead.
                encode_html(raw) if decoded else encode_html(raw, capture=capture),
                datetime.now(UTC),
                batch,
                error,
            )
