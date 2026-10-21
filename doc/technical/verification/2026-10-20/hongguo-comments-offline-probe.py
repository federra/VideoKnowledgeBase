"""Research-only parsing of public player preload JSON; no HTTP or business DB writes."""

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
from app.connectors.qidian_desktop import Document
from app.connectors.redfox import number

SERIES = "7697852455970671678"
SAVED = ROOT / f"data/hongguo/player-{SERIES}-2026-10-20.html"


def parse(html):
    scripts = [
        "".join(x for x in s.children if isinstance(x, str))
        for s in Document(html).root.all(tag="script")
    ]
    prefix = "_ROUTER_DATA = "
    candidates = [s[len(prefix):] for s in scripts if s.startswith(prefix)]
    if len(candidates) != 1:
        raise ValueError("Missing or ambiguous player preload")
    # Decode JSON only. Never execute downloaded JavaScript or parse request credentials.
    data, _ = json.JSONDecoder().raw_decode(candidates[0])
    page = data["loaderData"]["player_(series_id)/page"]
    if page.get("series_id") != SERIES or page.get("isSuccess") is not True:
        raise ValueError("Wrong series or unsuccessful page")
    detail, episode = page["seriesDetail"], page["vid"]
    if detail["series_id"] != SERIES or not re.fullmatch(r"[0-9]{1,32}", episode):
        raise ValueError("Invalid series/episode relationship")
    ids = detail["vid_list"]
    if ids.count(episode) != 1:
        raise ValueError("Missing or ambiguous episode position")
    review_block = page["episodeSocialInfo"]["reviews"]
    total, rows = number(review_block["total_count"]), review_block["reviews"]
    if not isinstance(rows, list) or len(rows) > 30:
        raise ValueError("Unverified sample shape")
    records = []
    for position, row in enumerate(rows):
        text, nickname, epoch = row.get("content"), row.get("user_name"), row.get("create_time")
        if not isinstance(text, str) or not text.strip() or not isinstance(nickname, str):
            raise ValueError("Missing comment text or nickname")
        if not isinstance(epoch, str) or not re.fullmatch(r"[0-9]{1,12}", epoch):
            raise ValueError("Unverified timestamp")
        diggs = number(row.get("digg_count"))
        records.append({
            "source_position": position, "platform_comment_id": None, "platform_user_id": None,
            "source_locator": f"episodeSocialInfo.reviews.reviews[{position}]",
            "series_id": SERIES, "page_episode_id": episode, "page_episode_number": ids.index(episode) + 1,
            "nickname": nickname, "content": text, "create_time_raw": epoch,
            "created_at": datetime.fromtimestamp(int(epoch), UTC).astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
            "digg_count": str(diggs) if diggs is not None else None,
            "avatar_present": bool(row.get("user_avatar")),
        })
    return {"series_id": SERIES, "series_title": detail["series_name"], "page_episode_id": episode,
            "page_episode_number": ids.index(episode) + 1, "total_count_reported": total,
            "loaded_count": len(records), "comment_scope": "player_preload_context", "cross_episode_pool_verified": False,
            "comments": records}


def main():
    raw = SAVED.read_bytes()
    capture = json.loads(SAVED.with_name("player-probe-2026-10-20.json").read_text())
    if capture["http_status"] != 200 or hashlib.sha256(raw).hexdigest() != capture["sha256"]:
        raise ValueError("Capture evidence mismatch")
    result = parse(raw.decode("utf-8"))
    checks = {"fifteen_comments_loaded": result["loaded_count"] == 15,
              "first_episode_verified": result["page_episode_number"] == 1,
              "sample_not_full_total": result["loaded_count"] < result["total_count_reported"],
              "all_comments_have_text_time_nickname": all(r["content"] and r["nickname"] and r["created_at"] for r in result["comments"]),
              "no_fabricated_platform_ids": all(r["platform_comment_id"] is None and r["platform_user_id"] is None for r in result["comments"])}
    if not all(checks.values()):
        raise ValueError("Comment sample verification failed")
    local = SAVED.with_name("comments-first-episode-sample.json")
    fd = os.open(local, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    public = [{k: v for k, v in r.items() if k not in ("content", "nickname")} | {
        "nickname_present": bool(r["nickname"]), "content_length": len(r["content"]),
        "content_sha256": hashlib.sha256(r["content"].encode()).hexdigest(),
    } for r in result["comments"]]
    summary = {k: v for k, v in result.items() if k != "comments"}
    evidence = {"capture": capture, **summary, "checks": checks, "comments": public,
                "missing_fields": ["platform_comment_id", "platform_user_id", "cursor", "has_more", "replies"],
                "offline_external_calls": 0, "business_database_writes": 0}
    Path(__file__).with_name("hongguo-comments-probe.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary | {"checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
