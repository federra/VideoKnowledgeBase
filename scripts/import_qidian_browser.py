"""Preview/import one frozen native-browser capture. Never opens a URL or browser."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from collect_qidian_mobile import fanqie_fingerprint

from app.collection.qidian_browser import run_browser, submit_browser
from app.connectors.qidian_browser import discover, document, normalize
from app.connectors.qidian_desktop import read_saved
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.novels import feed
from app.intelligence.service import shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal


def monthly_fingerprint(c, org):
    # Unchanged accepted board: source, frozen job, snapshot and entries (including exact IDs).
    rows = c.exec_driver_sql(
        "SELECT to_jsonb(s),to_jsonb(j),to_jsonb(n),to_jsonb(e),to_jsonb(o) "
        "FROM sources s JOIN collection_jobs j ON j.org_id=s.org_id AND j.source_id=s.id "
        "JOIN intelligence_snapshots n ON n.org_id=j.org_id AND n.job_id=j.id "
        "JOIN snapshot_entries e ON e.org_id=n.org_id AND e.snapshot_id=n.id "
        "JOIN content_observations o ON o.org_id=e.org_id AND o.id=e.content_observation_id "
        "WHERE s.org_id=%s AND s.board_code='qidian:desktop:female:yuepiao' ORDER BY n.id,e.id",
        (org,),
    ).all()
    return hashlib.sha256(
        json.dumps([list(r) for r in rows], sort_keys=True).encode()
    ).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    text, sha, size = read_saved(args.capture)
    doc = document(text)
    board = next(b for b in discover(text) if b["source_url"] == doc["url"])
    if board["rank_type"] == "yuepiao":
        raise ValueError("Accepted monthly board must remain unchanged")
    batch = normalize(board, text)
    record = {
        "board": board,
        "capture_kind": doc["capture_kind"],
        "sha256": sha,
        "bytes": size,
        "browser_observed_at": doc["captured_at"],
        "returned_items": batch.returned_items,
        "parsed_items": len(batch.records),
        "omitted_url_truncation": batch.returned_items - len(batch.records),
        "http_status": None,
        "import_http_requests": 0,
        "paid_calls": 0,
        "model_calls": 0,
        "business_date": str(shanghai_date()),
        "executed": False,
    }
    if not args.execute:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    engine = application_engine()
    saved = None
    try:
        with engine.begin() as c:
            _, context = enter(c)
            p = MemberPrincipal(context["org_id"], context["member_id"])
            record["fanqie_before"] = fanqie_fingerprint(c, p.org_id)
            record["monthly_before"] = monthly_fingerprint(c, p.org_id)
            saved = submit_browser(c, p, board, text)
        try:
            record.update(
                **saved, **run_browser(engine, p.org_id, UUID(saved["task_id"]))
            )
        finally:
            with engine.begin() as c:
                source = (
                    c.exec_driver_sql(
                        "SELECT lock_version,enabled FROM sources WHERE org_id=%s AND id=%s",
                        (p.org_id, UUID(saved["source_id"])),
                    )
                    .mappings()
                    .one()
                )
                if source["enabled"]:
                    compare_and_swap(
                        c,
                        "sources",
                        p.org_id,
                        UUID(saved["source_id"]),
                        source["lock_version"],
                        {"enabled": False},
                    )
        with engine.begin() as c:
            record["fanqie_unchanged"] = record["fanqie_before"] == fanqie_fingerprint(
                c, p.org_id
            )
            record["monthly_unchanged"] = record[
                "monthly_before"
            ] == monthly_fingerprint(c, p.org_id)
            record["displayed_total"] = feed(
                c,
                p,
                "motion_comic",
                shanghai_date(),
                platform="qidian",
                gender="female",
                rank_type=board["rank_type"],
            )["total"]
            record["collection_call_count"] = c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s AND job_id=%s",
                (p.org_id, UUID(saved["job_id"])),
            ).scalar_one()
            record["raw_sha_matches"] = c.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM task_inputs i JOIN raw_assets r ON r.org_id=i.org_id AND r.id=i.raw_asset_id WHERE i.org_id=%s AND i.task_id=%s AND i.role='novel_browser_ax' AND r.sha256=%s)",
                (p.org_id, UUID(saved["task_id"]), sha),
            ).scalar_one()
        record["executed"] = record["run_outcome"] != "ignored"
        record["sources_paused"] = True
        if record["task_state"] != "succeeded" or not all(
            record[k]
            for k in ("fanqie_unchanged", "monthly_unchanged", "raw_sha_matches")
        ):
            raise RuntimeError("Import/isolation validation failed")
        output = (
            ROOT / f"data/qidian/browser-{board['rank_type']}-{shanghai_date()}.json"
        )
        try:
            with output.open("x") as f:
                f.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        except FileExistsError:
            record["receipt_reused"] = True
        print(json.dumps(record, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
