"""Explicit dedicated-browser session; never attaches to a daily browser profile."""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.connectors.douyin_browser_session import (
    BINARIES,
    SESSION,
    exclusive_profile,
    guarded_capture,
    open_context,
    prepare,
    prepare_search_verification,
)


async def capture(path, limit, headed):
    from playwright.async_api import async_playwright

    selected = json.loads(path.read_text())[:limit]
    directory = SESSION / "captures"
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    results = []
    with exclusive_profile():
        async with async_playwright() as p:
            context = await open_context(p, headless=not headed)
            try:
                for entry in selected:
                    sid = entry["platform_content_id"].split(":", 1)[1]
                    result = await guarded_capture(context, sid, entry["platform_uid"])
                    result["snapshot_id"] = entry["snapshot_id"]
                    filename = directory / (
                        datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                        + "-"
                        + sid
                        + ".json"
                    )
                    with os.fdopen(
                        os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                        "w",
                    ) as file:
                        json.dump(result, file, ensure_ascii=False, default=str)
                    results.append(result)
                    print(
                        json.dumps(
                            {
                                "series_id": sid,
                                "status": result["status"],
                                "comments": len(result["comments"]),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if result["status"] != "sampled":
                        break
            finally:
                await context.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "capture", "verify-search"])
    parser.add_argument("--series-id", default="7560596669515958308")
    parser.add_argument(
        "--selected",
        type=Path,
        default=ROOT / "data/douyin/creator-series-probe/selected-top30.json",
    )
    parser.add_argument("--limit", type=int, default=1, choices=range(1, 31))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BINARIES))
    if args.action == "prepare":
        if not args.series_id.isascii() or not args.series_id.isdecimal():
            raise ValueError("Invalid public series ID")
        asyncio.run(prepare(args.series_id))
    elif args.action == "verify-search":
        asyncio.run(prepare_search_verification())
    else:
        asyncio.run(capture(args.selected, args.limit, args.headed))


if __name__ == "__main__":
    main()
