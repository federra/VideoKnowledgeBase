"""Parse public native accessibility captures; never synthesize HTML or HTTP replies."""

import json
import re
from datetime import datetime

from app.connectors.qidian_desktop import MAX_BYTES
from app.connectors.redfox import AdapterError, Batch

METHOD = "qidian-browser-ax-v1"
CAPTURE = "browser_native_accessibility"


def document(text):
    try:
        if len(text.encode()) > MAX_BYTES:
            raise ValueError
        d = json.loads(text)
        moment = datetime.fromisoformat(d["captured_at"])
        if (
            d["capture_kind"] != CAPTURE
            or d["page"] != 1
            or moment.tzinfo is None
            or not re.fullmatch(r"https://www\.qdmm\.com/rank/[a-z]{1,30}/", d["url"])
            or not isinstance(d["body"], str)
            or not re.search(r"^\t*\d+ HTML 内容 .*起点女生", d["body"])
        ):
            raise ValueError
        return d
    except (ValueError, TypeError, KeyError, AttributeError):
        raise AdapterError("INVALID_RESPONSE") from None


def discover(text):
    d = document(text)
    rows = re.findall(
        r"^\t*\d+ link ([^\n]+), Value: qdmm\.com/rank/([a-z]{1,30})/\s*$", d["body"], re.MULTILINE
    )
    out = {}
    for label, kind in rows:
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
            "code": f"qidian:browser:female:{kind}",
            "source_url": f"https://www.qdmm.com/rank/{kind}/",
            "name": label + " · 女频",
        }
    if not out or len(out) > 30:
        raise AdapterError("SOURCE_UNAVAILABLE")
    return list(out.values())


def normalize(board, text):
    d = document(text)
    matched = next((b for b in discover(text) if b["source_url"] == d["url"]), None)
    if matched is None or any(board.get(k) != v for k, v in matched.items()):
        raise AdapterError("INVALID_INPUT")
    body = d["body"]
    if not re.search(
        r"^\t*\d+ 标题 " + re.escape(board["rank_name"]) + r"(?:, Value: \d+)?$", body, re.MULTILINE
    ) or not re.search(r"^\t*\d+ 文本栏 \(settable\) 1$", body, re.MULTILINE):
        raise AdapterError("INVALID_RESPONSE")
    items = list(
        re.finditer(
            r"^\t*\d+ link (?![^\n]*, Help:)([^\n]+)在线阅读, Value: ([^\n]+)$", body, re.MULTILINE
        )
    )
    records, genres, seen, truncated = [], [], set(), False
    for i, item in enumerate(items[:30], 1):
        previous = body[: item.start()].splitlines()[-1]
        explicit = re.fullmatch(r"\t*\d+ 文本 (\d+)", previous)
        if not explicit and board["rank_type"] != "readindex":
            raise AdapterError("INVALID_RESPONSE")
        rank, title, href = int(explicit[1]) if explicit else i, item[1], item[2]
        if rank != i:
            raise AdapterError("INVALID_RESPONSE")
        if href == "…":
            truncated = True
            continue
        link = re.fullmatch(r"qdmm\.com/book/(\d{1,20})/", href)
        if not link or truncated or link[1] in seen or not title:
            raise AdapterError("INVALID_RESPONSE")
        seen.add(link[1])
        block = body[item.start() : items[i].start() if i < len(items) else len(body)]
        title_link = re.search(
            r"^\t*\d+ link "
            + re.escape(title)
            + r"(?:, Help: [^\n]*)?, Value: qdmm\.com/book/(\d{1,20})/$",
            block,
            re.MULTILINE,
        )
        if not title_link or title_link[1] != link[1]:
            raise AdapterError("INVALID_RESPONSE")
        author = re.search(r"^\t*\d+ link (.+), Value: qdmm\.com/author/\d+/$", block, re.MULTILINE)
        own = re.findall(
            r"^\t*\d+ link (.+), Value: qdmm\.com/(?:[a-z]+|all/chanId\d+-subCateId\d+/)$",
            block,
            re.MULTILINE,
        )
        for genre in own[:1]:
            if genre not in genres:
                genres.append(genre)
        intro = re.search(r"^\t*\d+ (?:text|文本) (?:连载|完本) (.*)$", block, re.MULTILINE)
        metric = re.search(
            r"^\t*\d+ (?:text|文本) ([^\n]+ (?:推荐|收藏|更新字数|字数|月票|书友))$",
            block,
            re.MULTILINE,
        )
        meta = {
            "kind": "novel-v1",
            "title": title,
            "author": author[1] if author else None,
            "reader_count": None,
            "rank": rank,
            "board": board,
            "word_count": None,
            "ranking_value_raw": metric[1] if metric else None,
            "ranking_value_encoded": bool(metric and any(ord(c) > 0xFFFF for c in metric[1])),
            "ranking_period": {"scope": "default", "page_title": body.splitlines()[0]},
            "ranking_position_basis": "explicit_rank" if explicit else "page_order",
            "work_fields": {"gender": None, "genres": own},
        }
        records.append(
            {
                "platform_content_id": link[1],
                "platform_uid": None,
                "account_display_name": meta["author"],
                "aliases": [],
                "provider_rank": rank,
                "content": {
                    "description": intro[1] or None if intro else None,
                    "original_url": "https://www." + href,
                    "cover_url": None,
                    "source_type_raw": "novel",
                    "view_count": None,
                    "source_tags": [meta],
                },
            }
        )
    if not records:
        raise AdapterError("SOURCE_UNAVAILABLE")
    for record in records:
        record["content"]["source_tags"][0]["taxonomy"] = genres
    return Batch("board", records, len(items))
