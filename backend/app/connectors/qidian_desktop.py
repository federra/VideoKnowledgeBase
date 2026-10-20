"""Public desktop female HTML. Never executes scripts or treats overview previews as ranks."""

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from app.connectors.redfox import AdapterError, Batch

METHOD = "qidian-desktop-html-v1"
HOST = "www.qdmm.com"
MAX_BYTES = 3 * 1024 * 1024


class Node:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def all(self, *, tag=None, cls=None, ident=None):
        result = []
        for child in self.children:
            if not isinstance(child, Node):
                continue
            if (
                (tag is None or child.tag == tag)
                and (cls is None or cls in child.attrs.get("class", "").split())
                and (ident is None or child.attrs.get("id") == ident)
            ):
                result.append(child)
            result.extend(child.all(tag=tag, cls=cls, ident=ident))
        return result

    def text(self):
        if self.tag in ("style", "script"):
            return ""
        return " ".join(x.text() if isinstance(x, Node) else x for x in self.children).strip()


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in (
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        ):
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def one(nodes):
    if len(nodes) != 1:
        raise AdapterError("INVALID_RESPONSE")
    return nodes[0]


def official_path(href):
    url = urlsplit(href)
    if (
        url.scheme not in ("", "https")
        or url.hostname != HOST
        or url.username
        or url.password
        or url.port
        or url.query
        or url.fragment
    ):
        raise AdapterError("INVALID_RESPONSE")
    return url.path


def discover(html):
    root = Document(html).root
    title = one(root.all(tag="title")).text()
    if "起点女生" not in title:
        raise AdapterError("SOURCE_UNAVAILABLE")
    nav = one(root.all(cls="rank-nav-list"))
    out = {}
    for a in nav.all(tag="a"):
        path = official_path(a.attrs.get("href", ""))
        if path == "/rank/":
            continue
        match = re.fullmatch(r"/rank/([a-z]{1,30})/", path)
        label = a.text()
        if not match or not label or len(label) > 30:
            raise AdapterError("INVALID_RESPONSE")
        kind = match[1]
        if kind in out and out[kind]["rank_name"] != label:
            raise AdapterError("INVALID_RESPONSE")
        out[kind] = {
            "platform": "qidian",
            "method": METHOD,
            "rank_type": kind,
            "rank_name": label,
            "gender": "female",
            "category_id": "all",
            "category_name": "全站",
            "code": f"qidian:desktop:female:{kind}",
            "source_url": "https://" + HOST + path,
            "name": label + " · 女频",
        }
    if not out or len(out) > 30:
        raise AdapterError("INVALID_RESPONSE")
    return list(out.values())


def normalize(board, html):
    matched = next((b for b in discover(html) if b["code"] == board.get("code")), None)
    if matched is None or any(board.get(k) != v for k, v in matched.items()):
        raise AdapterError("INVALID_INPUT")
    root = Document(html).root
    header = one(root.all(cls="rank-header"))
    if one(header.all(tag="h3")).text() != board["rank_name"]:
        raise AdapterError("INVALID_RESPONSE")
    pager = one(root.all(ident="page-container"))
    if pager.attrs.get("data-page") != "1":
        raise AdapterError("INVALID_RESPONSE")
    toolbar = one(header.all(cls="rank-toolbar-wrap"))
    channel_filters = [
        a for a in toolbar.all(tag="a", cls="act") if a.attrs.get("data-filter-key") == "chanId"
    ]
    if one(channel_filters).attrs.get("data-filter-value") != "-1":
        raise AdapterError("INVALID_RESPONSE")
    period = {k: toolbar.attrs.get("data-" + k) for k in ("year", "month")}
    items = one(root.all(ident="book-img-text")).all(tag="li")
    if not items:
        raise AdapterError("SOURCE_UNAVAILABLE")
    records, seen, genres = [], set(), []
    for i, li in enumerate(items[:30], 1):
        mid = one(li.all(cls="book-mid-info"))
        a = one(one(mid.all(tag="h2")).all(tag="a"))
        path = official_path(a.attrs.get("href", ""))
        match = re.fullmatch(r"/book/([0-9]{1,20})/", path)
        rank = one(li.all(cls="rank-tag")).text()
        if (
            not match
            or a.attrs.get("data-bid") != match[1]
            or not a.text()
            or rank != str(i)
            or match[1] in seen
        ):
            raise AdapterError("INVALID_RESPONSE")
        seen.add(match[1])
        author_node = one(mid.all(cls="author"))
        authors = author_node.all(tag="a", cls="name")
        author = one(authors).text() if authors else None
        own_genres = [x.text() for x in author_node.all(tag="a") if x not in authors and x.text()]
        for genre in own_genres[:1]:
            if genre not in genres:
                genres.append(genre)
        intros = mid.all(cls="intro")
        totals = li.all(cls="total")
        metric = one(totals).text() if totals else None
        meta = {
            "kind": "novel-v1",
            "title": a.text(),
            "author": author,
            "reader_count": None,
            "rank": i,
            "board": board,
            "word_count": None,
            "ranking_value_raw": metric,
            "ranking_value_encoded": bool(metric and any(ord(c) > 0xFFFF for c in metric)),
            "ranking_period": period,
            "work_fields": {"gender": None, "genres": own_genres},
        }
        records.append(
            {
                "platform_content_id": match[1],
                "platform_uid": None,
                "account_display_name": author,
                "aliases": [],
                "provider_rank": i,
                "content": {
                    "description": one(intros).text() or None if intros else None,
                    "original_url": "https://" + HOST + path,
                    "cover_url": None,
                    "source_type_raw": "novel",
                    "view_count": None,
                    "source_tags": [meta],
                },
            }
        )
    for record in records:
        record["content"]["source_tags"][0]["taxonomy"] = genres
    return Batch("board", records, len(items))


def read_saved(path):
    with Path(path).open("rb") as f:
        data = f.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise AdapterError("INVALID_RESPONSE")
    try:
        html = data.decode("utf-8")  # Preserve UTF-8 BOM in original evidence and byte hash.
    except UnicodeError:
        raise AdapterError("INVALID_RESPONSE") from None
    return html, hashlib.sha256(data).hexdigest(), len(data)


def inspect_saved_catalog(path):
    html, sha, size = read_saved(path)
    boards = discover(html)
    return {
        "capture_kind": "user_saved_html",
        "source_url": "https://" + HOST + "/rank/",
        "http_status": None,
        "sha256": sha,
        "bytes": size,
        "board_count": len(boards),
        "published_books": 0,
        "boards": boards,
    }
