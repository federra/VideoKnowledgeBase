"""Research-only offline extraction of a saved Hongguo page; never makes HTTP calls."""

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
from app.connectors.novel_metrics import reader_number
from app.connectors.qidian_desktop import Document

URL = "https://hongguoduanju.com/rank/hot-drama"
SAVED = ROOT / "data/hongguo/hot-drama-2026-10-20.html"


def one(values):
    if len(values) != 1:
        raise ValueError("Missing or ambiguous public field")
    return values[0]


def prefixed(node, tag, prefix):
    return [
        n for n in node.all(tag=tag)
        if any(c.startswith(prefix) for c in n.attrs.get("class", "").split())
    ]


def parse(html):
    root = Document(html).root
    if one(root.all(tag="h1")).text() != "红果热播榜":
        raise ValueError("Wrong ranking")
    canonical = one([n for n in root.all(tag="link") if n.attrs.get("rel") == "canonical"])
    if canonical.attrs.get("href") != URL:
        raise ValueError("Wrong page or page number")
    listing = one([n for n in root.all(tag="ol") if n.attrs.get("aria-label") == "红果热播榜"])
    updates = one([n.text() for n in root.all(tag="p") if "已更新" in n.text()])
    records = []
    for position, card in enumerate(listing.all(tag="article"), 1):
        title = one(card.all(tag="h2"))
        match = re.fullmatch(r"rank-title-([0-9]{1,32})", title.attrs.get("id", ""))
        if not match or card.attrs.get("aria-labelledby") != title.attrs["id"]:
            raise ValueError("Invalid series identity")
        series_id = match[1]
        links = [n for n in card.all(tag="a") if n.all(tag="h2")]
        detail = urlsplit(urljoin(URL, one(links).attrs.get("href", "")))
        if (detail.scheme != "https" or detail.netloc != "hongguoduanju.com"
                or detail.path != "/detail" or parse_qs(detail.query) != {"series_id": [series_id]}):
            raise ValueError("Mismatched series link")
        rank = int(one(prefixed(card, "span", "pc-badge-number-")).text())
        if rank != position:
            raise ValueError("Non-contiguous ranking")
        heat = one(prefixed(card, "p", "pc-metrics-")).text()
        if not heat.endswith("热度"):
            raise ValueError("Unverified metric meaning")
        engagement = one([n for n in card.all(tag="ul") if n.attrs.get("aria-label") == "作品互动数据"])
        values = [n.text() for n in engagement.all(tag="li")]
        collect = one([v for v in values if v.endswith("收藏")])
        like = one([v for v in values if v.endswith("点赞")])
        rating = one([v for v in values if v.startswith("评分")])
        if not re.fullmatch(r"评分(?:[0-9](?:\.[0-9])?|10(?:\.0)?)", rating):
            raise ValueError("Invalid rating")
        description = one(prefixed(card, "p", "pc-description-")).text()
        categories = one(prefixed(card, "p", "pc-categories-"))
        records.append({
            "rank": rank, "series_id": series_id, "title": title.text(),
            "original_url": detail.geturl(), "description": description,
            "tags": [n.text() for n in categories.all(tag="span")],
            "heat_raw": heat, "heat_display_value": str(reader_number(heat.removesuffix("热度"))),
            "collect_raw": collect,
            "collect_display_value": str(reader_number(collect.removesuffix("收藏"))),
            "like_raw": like, "like_display_value": str(reader_number(like.removesuffix("点赞"))),
            "rating_raw": rating, "rating_display_value": rating.removeprefix("评分"),
            "metric_precision": "website_display_rounded", "view_count": None,
            "comment_count": None, "share_count": None, "total_episodes": None,
        })
    if not records or len(records) > 30 or len({r["series_id"] for r in records}) != len(records):
        raise ValueError("Invalid or duplicate ranking records")
    return updates, records


def main():
    raw = SAVED.read_bytes()
    metadata = json.loads((SAVED.parent / "probe-2026-10-20.json").read_text())
    if metadata["http_status"] != 200 or metadata["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("Capture evidence mismatch")
    updates, records = parse(raw.decode("utf-8"))
    checks = {
        "twenty_first_page_records": len(records) == 20,
        "all_titles_descriptions_tags": all(r["title"] and r["description"] and r["tags"] for r in records),
        "all_ranks_and_ids_validated": True,
        "all_heat_like_collect_rating_extracted": all(
            r[k] for r in records for k in ["heat_raw", "like_raw", "collect_raw", "rating_raw"]
        ),
        "heat_not_play_count": all(r["view_count"] is None for r in records),
    }
    if not all(checks.values()):
        raise ValueError("Research validation failed")
    (SAVED.parent / "parsed-first-page.json").write_text(
        json.dumps({"updated_text": updates, "records": records}, ensure_ascii=False, indent=2) + "\n"
    )
    public = [{k: v for k, v in r.items() if k != "description"} | {"description_length": len(r["description"])} for r in records]
    result = {"capture": metadata, "updated_text": updates, "record_count": len(records),
              "offline_external_calls": 0, "database_writes": 0, "checks": checks, "records": public}
    target = Path(__file__).with_name("hongguo-rank-probe.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"record_count": len(records), "checks": checks, "first_three": public[:3]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
