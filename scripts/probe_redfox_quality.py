"""One explicitly authorized quality-library video search. Private response; no pagination/retry."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.connectors.redfox import safe_evidence
from app.core.config import settings

REQUEST = {"keyword": "漫剧", "offset": 0, "sortType": "_4"}
URL = "https://redfox.hk/story/api/dyData/searchArticle"


def fetch_once(key, *, transport=None):
    with (
        httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client,
        client.stream(
            "POST",
            URL,
            headers={"REDFOX_API_KEY": key, "Accept-Encoding": "identity"},
            json=REQUEST,
        ) as response,
    ):
        raw = bytearray()
        truncated = False
        for chunk in response.iter_bytes():
            if len(raw) + len(chunk) > 1024 * 1024:
                raw.extend(chunk[: 1024 * 1024 - len(raw)])
                truncated = True
                break
            raw.extend(chunk)
        text = safe_evidence(bytes(raw), key, truncated=truncated)
        summary = {
            "http_status": response.status_code,
            "success": False,
            "request": REQUEST,
            "requests_made": 1,
            "returned_items": 0,
            "inspected_top_items": 0,
            "row_fields": [],
            "view_metric_fields": [],
            "can_verify_play_count": False,
            "truncated": truncated,
        }
        try:
            value = json.loads(text)
            rows = value.get("data", {}).get("list", []) if isinstance(value, dict) else []
            summary["provider_code"] = value.get("code") if isinstance(value, dict) else None
            if (
                response.status_code == 200
                and summary["provider_code"] == 2000
                and isinstance(rows, list)
                and all(isinstance(x, dict) for x in rows)
                and not truncated
            ):
                top = rows[:10]
                summary.update(
                    success=True,
                    returned_items=len(rows),
                    inspected_top_items=len(top),
                    row_fields=sorted({k for r in top for k in r}),
                )
                summary["view_metric_fields"] = [
                    k
                    for k in summary["row_fields"]
                    if any(x in k.lower() for x in ["play", "view", "read"])
                ]
                # A field name alone never proves the supplier's metric definition.
        except (ValueError, AttributeError, TypeError):
            pass
        return text, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "request": REQUEST,
                    "paid_call": False,
                    "max_requests": 1,
                    "max_inspected_items": 10,
                },
                ensure_ascii=False,
            )
        )
        return
    if not settings.redfox_api_key or not settings.redfox_api_key.get_secret_value().strip():
        raise RuntimeError("Key missing")
    directory = ROOT / "data/redfox"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "quality-views-probe-2026-10-17.json"
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(
            {
                "status": "reserved",
                "request": REQUEST,
                "requested_at": datetime.now(UTC).isoformat(),
                "max_requests": 1,
            },
            f,
        )
    try:
        raw, summary = fetch_once(settings.redfox_api_key.get_secret_value())
    except httpx.RequestError:
        marker.write_text(
            json.dumps({"status": "external_result_unknown", "requests_reserved": 1}) + "\n"
        )
        raise RuntimeError("External result unknown; no retry") from None
    raw_path = directory / "quality-views-probe-2026-10-17-response.json"
    fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw)
    summary.update(
        status="received",
        captured_at=datetime.now(UTC).isoformat(),
        raw_saved_privately=True,
        new_board_rows=0,
        new_model_calls=0,
    )
    marker.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - never print provider bodies, keys or HTTP exceptions
        print("Quality probe stopped: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
