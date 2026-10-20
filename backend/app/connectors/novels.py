"""Fixed official novel rankings. One public request, no cookies, search fallback or retries."""

import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from app.connectors.fontcodec import decode, spec
from app.connectors.novel_metrics import reader_number
from app.connectors.redfox import AdapterError, Batch, Reply, number

VERSION = "novel-public-v1"
CATALOG = "novel.fanqie.catalog"
QCATALOG = "novel.qidian.catalog"
CAPABILITIES = {CATALOG, QCATALOG, "novel.fanqie.board", "novel.qidian.board"}
RANK_NAMES = {"read": "阅读榜", "new": "新书榜"}
MAX_BYTES = 3 * 1024 * 1024


def initial(html):
    match = re.search("__INITIAL_STATE__\\s*=\\s*", html)
    if not match:
        raise AdapterError("INVALID_RESPONSE")
    text = html[match.end() : html.find("</script>", match.end())]
    text = re.sub(
        '"(?:[^"\\\\]|\\\\.)*"|\\bundefined\\b',
        lambda m: m.group() if m.group().startswith('"') else "null",
        text,
    )
    try:
        return json.JSONDecoder().raw_decode(text.strip())[0]
    except ValueError:
        raise AdapterError("INVALID_RESPONSE") from None


def catalog(html):
    state = initial(html)
    if not isinstance(state, dict) or not isinstance(state.get("rank"), dict):
        raise AdapterError("INVALID_RESPONSE")
    rank = state["rank"]
    if not isinstance(rank.get("rankCategoryTypeList"), dict):
        raise AdapterError("INVALID_RESPONSE")
    version = rank.get("rankVersion")
    out = []
    if not isinstance(version, str) or not version.isdecimal():
        raise AdapterError("INVALID_RESPONSE")
    for gender in ["male", "female"]:
        cats = rank.get("rankCategoryTypeList", {}).get(gender)
        if not isinstance(cats, list) or len(cats) > 100:
            raise AdapterError("INVALID_RESPONSE")
        for c in cats:
            if not isinstance(c, dict):
                raise AdapterError("INVALID_RESPONSE")
            ident = str(c.get("id", ""))
            name = c.get("name")
            if not ident.isdecimal() or not isinstance(name, str) or (not name):
                raise AdapterError("INVALID_RESPONSE")
            for kind in RANK_NAMES:
                out.append(
                    {
                        "platform": "fanqie",
                        "rank_type": kind,
                        "gender": gender,
                        "category_id": ident,
                        "category_name": name,
                        "rank_version": version,
                        "code": f"fanqie:{kind}:{gender}:{ident}",
                    }
                )
    if not out or len({x["code"] for x in out}) != len(out):
        raise AdapterError("INVALID_RESPONSE")
    return out


class QidianParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"href": dict(attrs).get("href", ""), "text": ""}

    def handle_data(self, data):
        if self.current:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current:
            self.links.append(self.current)
            self.current = None


def qidian_catalog(html):
    parser = QidianParser()
    parser.feed(html)
    out = {}
    for link in parser.links:
        url = urlsplit(link["href"])
        match = re.fullmatch("/rank/([a-z]+)/?", url.path)
        if match and (not url.netloc or url.hostname == "www.qidian.com") and link["text"].strip():
            kind = match[1]
            out[kind] = {
                "platform": "qidian",
                "rank_type": kind,
                "gender": "all",
                "category_id": "all",
                "category_name": "全部题材",
                "name": link["text"].strip(),
                "code": "qidian:" + kind,
            }
    if not out:
        raise AdapterError("SOURCE_UNAVAILABLE")
    return list(out.values())


def book_fields(book, *, decoder=None):
    """Only explicit work fields; ranking membership is not a work classification."""
    mapping = spec()["mapping"] if decoder is None else decoder

    def text(value):
        if not isinstance(value, str):
            return None
        try:
            return decode(value, mapping).strip() or None
        except AdapterError:
            return None

    gender = {"male": "male", "female": "female", "男频": "male", "女频": "female"}.get(
        text(book.get("gender"))
    )
    genres = []
    for field in ("categoryV2", "category"):
        value = text(book.get(field))
        if value and value not in genres:
            genres.append(value)
    return {"gender": gender, "genres": genres}


def captured_book_fields(raw_text):
    """Project legacy snapshots from their unchanged, authorized original response."""
    try:
        body = json.loads(raw_text)
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise AdapterError("INVALID_RESPONSE")
        books = body["data"].get("book_list")
        if not isinstance(books, list):
            raise AdapterError("INVALID_RESPONSE")
        result = {}
        for book in books[:30]:
            if not isinstance(book, dict) or not str(book.get("bookId", "")).isdecimal():
                raise AdapterError("INVALID_RESPONSE")
            result[str(book["bookId"])] = book_fields(book)
        return result
    except ValueError:
        raise AdapterError("INVALID_RESPONSE") from None


def normalize(board, body, *, decoder=None):
    mapping = spec()["mapping"] if decoder is None else decoder
    if (
        not isinstance(body, dict)
        or body.get("code") != 0
        or not isinstance(body.get("data"), dict)
        or not isinstance(body["data"].get("book_list"), list)
    ):
        raise AdapterError("INVALID_RESPONSE")
    books = body["data"]["book_list"]
    records = []
    seen = set()
    for i, b in enumerate(books[:30]):
        if not isinstance(b, dict):
            raise AdapterError("INVALID_RESPONSE")
        ident = str(b.get("bookId", ""))
        if not ident.isdecimal() or ident in seen:
            raise AdapterError("INVALID_RESPONSE")
        seen.add(ident)
        title = decode(b.get("bookName"), mapping)
        if not title or not title.strip():
            raise AdapterError("INVALID_RESPONSE")
        rank = b.get("currentPos", i + 1)
        if type(rank) is not int or rank < 1:
            raise AdapterError("INVALID_RESPONSE")
        meta = {
            "kind": "novel-v1",
            "title": title,
            "author": decode(b.get("author"), mapping),
            "reader_count": reader_number(b.get("read_count")),
            "rank": rank,
            "board": board,
            "word_count": number(b.get("wordNumber")),
            "work_fields": book_fields(b, decoder=mapping),
        }
        records.append(
            {
                "platform_content_id": ident,
                "platform_uid": None,
                "account_display_name": meta["author"],
                "aliases": [],
                "provider_rank": rank,
                "content": {
                    "description": decode(b.get("abstract"), mapping),
                    "original_url": "https://fanqienovel.com/page/" + ident,
                    "cover_url": None,
                    "source_type_raw": "novel",
                    "view_count": None,
                    "source_tags": [meta],
                },
            }
        )
    return Batch("board", records, len(books))


class PublicNovels:
    def __init__(self, client=None, decoder=None):
        self.client = client
        self.decoder = decoder

    def ready(self):
        pass

    def fetch(self, capability, request, *, maximum):
        if capability not in CAPABILITIES or type(maximum) is not int or (not 1 <= maximum <= 30):
            raise AdapterError("INVALID_INPUT")
        params = None
        if capability == CATALOG:
            url = "https://fanqienovel.com/rank"
        elif capability == QCATALOG:
            url = "https://www.qidian.com/rank/"
        elif capability == "novel.fanqie.board":
            if (
                request.get("rank_type") not in RANK_NAMES
                or request.get("gender") not in ["male", "female"]
                or (not str(request.get("category_id", "")).isdecimal())
                or (not str(request.get("rank_version", "")).isdecimal())
            ):
                raise AdapterError("INVALID_INPUT")
            if self.decoder is None and request.get("font_sha256") != spec()["font_sha256"]:
                raise AdapterError("SOURCE_UNAVAILABLE")
            url = "https://fanqienovel.com/api/rank/category/list"
            params = {
                "app_id": 2503,
                "rank_list_type": 3,
                "offset": 0,
                "limit": maximum,
                "category_id": request["category_id"],
                "rank_version": request["rank_version"],
                "gender": 1 if request["gender"] == "male" else 0,
                "rankMold": 2 if request["rank_type"] == "read" else 1,
            }
        else:
            if not re.fullmatch("[a-z]+", request.get("rank_type", "")):
                raise AdapterError("INVALID_INPUT")
            url = "https://www.qidian.com/rank/" + request["rank_type"] + "/"
        owned = self.client is None
        client = self.client or httpx.Client(timeout=20, follow_redirects=False)
        text = ""
        status = None
        batch = None
        error = None
        outcome = "network_error"
        try:
            with client.stream(
                "GET",
                url,
                params=params,
                headers={
                    "Accept": "application/json,text/html",
                    "Referer": "https://fanqienovel.com/rank"
                    if "fanqie" in capability
                    else "https://www.qidian.com/",
                },
            ) as response:
                status = response.status_code
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise AdapterError("INVALID_RESPONSE")
                    chunks.append(chunk)
                text = b"".join(chunks).decode("utf-8")
            if status != 200:
                error = "SOURCE_UNAVAILABLE"
                outcome = "http_error"
            elif capability == CATALOG:
                catalog(text)
                outcome = "success"
            elif capability == QCATALOG:
                qidian_catalog(text)
                outcome = "success"
            elif capability == "novel.fanqie.board":
                batch = normalize(request, json.loads(text), decoder=self.decoder)
                batch.records = batch.records[:maximum]
                outcome = "success"
            else:
                raise AdapterError("SOURCE_UNAVAILABLE")
        except (AdapterError, ValueError, UnicodeError):
            error = "SOURCE_UNAVAILABLE"
            outcome = "invalid_shape"
        except httpx.HTTPError:
            error = "NETWORK_ERROR"
        finally:
            if owned:
                client.close()
        return Reply(
            status, None, outcome, text or "[empty response]", datetime.now(UTC), batch, error
        )
