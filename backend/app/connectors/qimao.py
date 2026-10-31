"""Fixed official Qimao SSR rankings; no script execution, login, redirects or retries."""

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.connectors.novel_metrics import reader_number
from app.connectors.qidian_desktop import Document, one
from app.connectors.redfox import AdapterError, Batch, Reply

METHOD = "qimao-public-html-v1"
CAPABILITY = "novel.qimao.board"
MAX_BYTES = 3 * 1024 * 1024
RANKS = {
    "hot": "大热榜",
    "new": "新书榜",
    "over": "完结榜",
    "collect": "收藏榜",
    "update": "更新榜",
}
CHANNELS = {"male": "boy", "female": "girl"}


def boards():
    return [
        {
            "platform": "qimao",
            "method": METHOD,
            "rank_type": kind,
            "rank_name": name,
            "gender": gender,
            "category_id": "all",
            "category_name": "全站",
            "code": f"qimao:{gender}:{kind}",
            "name": f"{'男频' if gender == 'male' else '女频'} · {name}",
        }
        for gender in CHANNELS
        for kind, name in RANKS.items()
    ]


def validate_board(board):
    expected = next((b for b in boards() if b["code"] == board.get("code")), None)
    if expected is None or any(board.get(k) != v for k, v in expected.items()):
        raise AdapterError("INVALID_INPUT")
    return f"/paihang/{CHANNELS[board['gender']]}/{board['rank_type']}/date/"


def path(href):
    u = urlsplit(href)
    if (
        u.scheme not in ("", "https")
        or (u.netloc and u.netloc != "www.qimao.com")
        or u.query
        or u.fragment
    ):
        raise AdapterError("INVALID_RESPONSE")
    return u.path


def normalize(board, html):
    expected_path = validate_board(board)
    root = Document(html).root
    if "七猫" not in one(root.all(tag="title")).text():
        raise AdapterError("SOURCE_UNAVAILABLE")
    channel = [
        n
        for n in root.all(cls="item")
        if "active" in n.attrs.get("class", "").split() and n.text() in ("男生榜", "女生榜")
    ]
    if one(channel).text() != ("男生榜" if board["gender"] == "male" else "女生榜"):
        raise AdapterError("INVALID_RESPONSE")
    tab = one(
        [n for n in root.all(cls="child-tabs-item") if "active" in n.attrs.get("class", "").split()]
    )
    a = one(tab.all(tag="a"))
    if path(a.attrs.get("href", "")) != expected_path or a.text() != board["rank_name"]:
        raise AdapterError("INVALID_RESPONSE")
    date_tabs = root.all(cls="date-type-tabs")
    if board["rank_type"] in ("hot", "new", "over") or date_tabs:
        tabs = one(date_tabs)
        active = one(
            [
                a
                for a in tabs.all(tag="a", cls="tab")
                if "active" in a.attrs.get("class", "").split()
            ]
        )
        if active.text() != "日榜" or path(active.attrs.get("href", "")) != expected_path:
            raise AdapterError("INVALID_RESPONSE")
    pages = one(root.all(cls="rank-page"))
    if (
        one(
            [n for n in pages.all(cls="num") if "active" in n.attrs.get("class", "").split()]
        ).text()
        != "1"
    ):
        raise AdapterError("INVALID_RESPONSE")
    cards = root.all(tag="li", cls="rank-list-item")
    if not cards:
        raise AdapterError("SOURCE_UNAVAILABLE")
    records, seen = [], set()
    parsed = []
    for i, card in enumerate(cards[:20], 1):
        a = one(card.all(tag="a", cls="s-book-title"))
        match = re.fullmatch(r"/shuku/([0-9]+)/", path(a.attrs.get("href", "")))
        rank = one(card.all(cls="rank-number")).text()
        title = a.text()
        if not match or match[1] in seen or rank != str(i) or not title:
            raise AdapterError("INVALID_RESPONSE")
        ident = match[1]
        seen.add(ident)
        info = one(card.all(cls="s-book-info"))
        authors, genres = [], []
        for link in info.all(tag="a"):
            p = path(link.attrs.get("href", ""))
            if p.startswith("/zuozhe/"):
                authors.append(link.text())
            elif re.fullmatch(r"/shuku/[a-z0-9-]+/", p):
                label = link.text()
                if label and label not in genres:
                    genres.append(label)
        heat_value = heat_display = None
        for metric in card.all(cls="rank-change-num"):
            # Changes in ranking use the same number class, but are labeled 名, not 热度.
            if not re.search(r"\b热度\b", metric.text()):
                continue
            num = one(metric.all(cls="rank-num")).text()
            units = metric.all(cls="rank-unit")
            heat_display = num + (one(units).text() if units else "")
            heat_value = reader_number(heat_display)
        meta = {
            "kind": "novel-v1",
            "title": title,
            "author": authors[0] if len(authors) == 1 else None,
            "reader_count": None,
            "heat_value": heat_value,
            "heat_display": heat_display,
            "rank": i,
            "board": board,
            "word_count": None,
            "work_fields": {"gender": None, "genres": genres},
            "taxonomy": genres[:1],
            "category_path": genres,
        }
        parsed.append((ident, meta, one(card.all(cls="s-book-intro")).text()))
    taxonomy = sorted({g for _, meta, _ in parsed for g in meta["taxonomy"]})
    for ident, meta, description in parsed:
        # This board's observed first-level labels define its searchable taxonomy.
        meta["taxonomy"] = taxonomy
        records.append(
            {
                "platform_content_id": ident,
                "platform_uid": None,
                "account_display_name": meta["author"],
                "aliases": [],
                "provider_rank": meta["rank"],
                "content": {
                    "description": description or None,
                    "original_url": f"https://www.qimao.com/shuku/{ident}/",
                    "cover_url": None,
                    "source_type_raw": "novel",
                    "view_count": None,
                    "source_tags": [meta],
                },
            }
        )
    return Batch("board", records, len(cards))


class Qimao:
    def __init__(self, client=None):
        self.client = client

    def ready(self):
        pass

    def fetch(self, capability, request, *, maximum):
        if capability != CAPABILITY or maximum != 20:
            raise AdapterError("INVALID_INPUT")
        url = "https://www.qimao.com" + validate_board(request)
        owned = self.client is None
        client = self.client or httpx.Client(timeout=20, follow_redirects=False)
        chunks, status, batch, error = [], None, None, None
        outcome = "network_error"
        try:
            with client.stream(
                "GET",
                url,
                follow_redirects=False,
                headers={"Accept": "text/html", "Referer": "https://www.qimao.com/paihang/"},
            ) as r:
                status, size = r.status_code, 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise AdapterError("INVALID_RESPONSE")
                    chunks.append(chunk)
            text = b"".join(chunks).decode("utf-8")
            if status != 200:
                error, outcome = "SOURCE_UNAVAILABLE", "http_error"
            else:
                batch, outcome = normalize(request, text), "success"
        except (AdapterError, UnicodeError):
            error, outcome = "SOURCE_UNAVAILABLE", "invalid_shape"
        except httpx.HTTPError:
            error = "NETWORK_ERROR"
        finally:
            if owned:
                client.close()
        return Reply(
            status,
            None,
            outcome,
            b"".join(chunks).decode("utf-8", errors="replace") or "[empty response]",
            datetime.now(UTC),
            batch,
            error,
        )
