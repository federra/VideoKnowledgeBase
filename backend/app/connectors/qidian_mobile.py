"""Official mobile SSR rankings, independently implemented from NovelCrawler's method."""

import base64
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from app.connectors.redfox import AdapterError, Batch, Reply

METHOD = "novelcrawler-mobile-v1"
HOSTS = {"male": "m.qidian.com", "female": "m.qdmm.com"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def state(html, gender, *, index=False):
    for text in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        if not text.strip().startswith("{"):
            continue
        try:
            root = json.loads(text)
        except ValueError:
            continue
        if not isinstance(root, dict) or not isinstance(root.get("pageContext"), dict):
            continue
        pc = root["pageContext"]
        props = pc.get("pageProps")
        route = pc.get("routeParams")
        expected = "/src/pages/rank/index" if index else "/src/pages/rankDetail/index"
        if pc.get("_pageId") != expected:
            continue
        if (
            not isinstance(props, dict)
            or not isinstance(props.get("pageData"), dict)
            or not isinstance(route, dict)
        ):
            raise AdapterError("INVALID_RESPONSE")
        data = props["pageData"]
        if (
            pc.get("hostname") != HOSTS.get(gender)
            or route.get("gender") != gender
            or data.get("gender") != gender
        ):
            raise AdapterError("INVALID_RESPONSE")
        return data, route
    raise AdapterError("SOURCE_UNAVAILABLE")


class IndexLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.plain_span = False
        self.title = ""
        self.label = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "span" and not attrs:
            self.plain_span = True
            self.title = ""
        if tag == "a" and self.label:
            self.links.append((dict(attrs).get("href", ""), self.label))

    def handle_data(self, data):
        if self.plain_span:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "span" and self.plain_span:
            title = self.title.strip()
            if 0 < len(title) <= 20 and title.endswith("榜"):
                self.label = title
            self.plain_span = False


def discover(html, gender):
    state(html, gender, index=True)
    parser = IndexLinks()
    parser.feed(html)
    out = {}
    for href, label in parser.links:
        u = urlsplit(href)
        rank_match = re.fullmatch(r"/rank/([a-z]{1,30})/", u.path)
        if rank_match and u.hostname == HOSTS[gender]:
            kind = rank_match[1]
            out[kind] = {
                "platform": "qidian",
                "method": METHOD,
                "rank_type": kind,
                "rank_name": label,
                "gender": gender,
                "category_id": "all",
                "category_name": "全站",
                "code": f"qidian:mobile:{gender}:{kind}",
                "name": label + " · " + ("男频" if gender == "male" else "女频"),
            }
    if not out or len(out) > 20:
        raise AdapterError("INVALID_RESPONSE")
    return list(out.values())


def taxonomy(data):
    out = []
    for group in data.get("filters", []) if isinstance(data.get("filters"), list) else []:
        if not isinstance(group, dict) or group.get("key") != "catId":
            continue
        items = group.get("items", [])
        if not isinstance(items, list):
            raise AdapterError("INVALID_RESPONSE")
        for item in items:
            if not isinstance(item, dict):
                raise AdapterError("INVALID_RESPONSE")
            value = item.get("text")
            if item.get("value") in (-1, "-1") or not isinstance(value, str) or not value.strip():
                continue
            if value.strip() not in out:
                out.append(value.strip())
    return out


def own_fields(book):
    gender = (
        {"male": "male", "female": "female", "男频": "male", "女频": "female"}.get(
            book.get("gender")
        )
        if isinstance(book.get("gender"), str)
        else None
    )
    genres = []
    for key in ("cat", "catName", "subCat"):
        value = book.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in genres:
            genres.append(value.strip())
    return {"gender": gender, "genres": genres}


def normalize(board, html):
    data, route = state(html, board["gender"])
    if (
        route.get("pageType") != board["rank_type"]
        or type(data.get("pageNum")) is not int
        or data["pageNum"] != 1
        or not isinstance(data.get("records"), list)
    ):
        raise AdapterError("INVALID_RESPONSE")
    records = []
    seen = set()
    genres = taxonomy(data)
    for i, book in enumerate(data["records"][:30]):
        if not isinstance(book, dict):
            raise AdapterError("INVALID_RESPONSE")
        ident = str(book.get("bid", book.get("bookId", "")))
        title = book.get("bName", book.get("bookName"))
        rank = book.get("rankNum")
        if (
            not ident.isdecimal()
            or ident in seen
            or not isinstance(title, str)
            or not title.strip()
            or type(rank) is not int
            or rank < 1
        ):
            raise AdapterError("INVALID_RESPONSE")
        seen.add(ident)

        def text(*keys, book=book):
            for key in keys:
                value = book.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return None

        author = text("bAuth", "authorName")
        meta = {
            "kind": "novel-v1",
            "title": title.strip(),
            "author": author,
            "reader_count": None,
            "rank": rank,
            "board": board,
            "word_count": None,
            "word_count_raw": text("cnt", "wordCount"),
            "ranking_value_raw": text("rankCnt"),
            "taxonomy": genres,
            "work_fields": own_fields(book),
        }
        records.append(
            {
                "platform_content_id": ident,
                "platform_uid": None,
                "account_display_name": author,
                "aliases": [],
                "provider_rank": rank,
                "content": {
                    "description": text("desc", "introduction"),
                    "original_url": "https://" + HOSTS[board["gender"]] + "/book/" + ident + "/",
                    "cover_url": None,
                    "source_type_raw": "novel",
                    "view_count": None,
                    "source_tags": [meta],
                },
            }
        )
    return Batch("board", records, len(data["records"]))


class QidianMobile:
    def __init__(self, client=None):
        self.client = client

    def ready(self):
        pass

    def fetch(self, capability, request, *, maximum):
        if (
            capability not in ("novel.qidian.catalog", "novel.qidian.board")
            or maximum != 30
            or type(maximum) is not int
            or request.get("gender") not in HOSTS
            or request.get("method") != METHOD
        ):
            raise AdapterError("INVALID_INPUT")
        gender = request["gender"]
        kind = request.get("rank_type")
        if capability == "novel.qidian.catalog":
            if kind != "catalog":
                raise AdapterError("INVALID_INPUT")
            path = "/rank/"
        else:
            if not isinstance(kind, str) or not re.fullmatch("[a-z]{1,30}", kind):
                raise AdapterError("INVALID_INPUT")
            path = "/rank/" + kind + "/"
        url = "https://" + HOSTS[gender] + path
        owned = self.client is None
        client = self.client or httpx.Client(timeout=20, follow_redirects=False)
        text = ""
        received = bytearray()
        body_note = ""
        status = None
        batch = None
        error = None
        outcome = "network_error"
        try:
            with client.stream(
                "GET", url, headers={**HEADERS, "Referer": "https://" + HOSTS[gender] + "/"}
            ) as response:
                status = response.status_code
                for chunk in response.iter_bytes():
                    remaining = 3 * 1024 * 1024 - len(received)
                    received.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        body_note = "\n[truncated at 3 MiB]"
                        raise AdapterError("INVALID_RESPONSE")
                text = bytes(received).decode("utf-8")
            if status != 200:
                error = "SOURCE_UNAVAILABLE"
                outcome = "http_error"
            elif capability == "novel.qidian.catalog":
                discover(text, gender)
                outcome = "success"
            else:
                batch = normalize(request, text)
                outcome = "success"
        except (AdapterError, ValueError, UnicodeError):
            error = "SOURCE_UNAVAILABLE"
            outcome = "invalid_shape"
        except httpx.HTTPError:
            error = "NETWORK_ERROR"
            body_note = "\n[incomplete response; network error]"
        finally:
            if received:
                try:
                    text = bytes(received).decode("utf-8")
                except UnicodeError:
                    text = "[invalid UTF-8; base64 body]\n" + base64.b64encode(received).decode(
                        "ascii"
                    )
                text += body_note
            if status is not None and status != 200:
                error = "SOURCE_UNAVAILABLE"
                outcome = "http_error"
            if owned:
                client.close()
        return Reply(
            status, None, outcome, text or "[empty response]", datetime.now(UTC), batch, error
        )
