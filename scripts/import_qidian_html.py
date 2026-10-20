"""Inspect/import one user-saved Qidian female rank page. No HTTP requests."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from collect_qidian_mobile import fanqie_fingerprint

from app.collection.qidian_desktop import run_saved, submit_saved
from app.connectors.qidian_desktop import (
    discover,
    inspect_saved_catalog,
    normalize,
    read_saved,
)
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.novels import feed
from app.intelligence.service import shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(ROOT / "data/qidian/female-rank.html"))
    parser.add_argument("--rank", required=True)
    parser.add_argument("--kind", default="yuepiao")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    catalog = inspect_saved_catalog(args.catalog)
    html, sha, size = read_saved(args.rank)
    board = next(
        b for b in discover(read_saved(args.catalog)[0]) if b["rank_type"] == args.kind
    )
    batch = normalize(board, html)
    record = {
        "method": board["method"],
        "catalog": catalog,
        "board": board,
        "rank_file": {"sha256": sha, "bytes": size},
        "parsed_items": len(batch.records),
        "http_status": None,
        "external_requests": 0,
        "paid_calls": 0,
        "model_calls": 0,
        "capture_kind": "user_saved_html",
        "source_capture_time": None,
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
            saved = submit_saved(c, p, board, html)
        try:
            outcome = run_saved(engine, p.org_id, UUID(saved["task_id"]))
            state = outcome["task_state"]
            record.update(executed=outcome["run_outcome"] != "ignored", **outcome, **saved)
        finally:
            if saved:
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
            record["fanqie_after"] = fanqie_fingerprint(c, p.org_id)
            record["fanqie_unchanged"] = (
                record["fanqie_before"] == record["fanqie_after"]
            )
            result = feed(
                c,
                p,
                "motion_comic",
                shanghai_date(),
                platform="qidian",
                gender="female",
                rank_type=args.kind,
            )
            record.update(
                displayed_total=result["total"],
                genders=result["genders"],
                sources_paused=True,
            )
            record["raw_sha_matches_file"] = c.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM task_inputs i JOIN raw_assets r ON r.org_id=i.org_id AND r.id=i.raw_asset_id WHERE i.org_id=%s AND i.task_id=%s AND r.sha256=%s AND r.origin='manual')",
                (p.org_id, UUID(saved["task_id"]), sha),
            ).scalar_one()
            record["collection_call_count"] = c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s AND job_id=%s",
                (p.org_id, UUID(saved["job_id"])),
            ).scalar_one()
        output = ROOT / f"data/qidian/saved-{args.kind}-{shanghai_date()}.json"
        try:
            with output.open("x") as f:
                f.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        except FileExistsError:
            record["receipt_reused"] = True
        if state != "succeeded" or not record["fanqie_unchanged"]:
            raise RuntimeError("Import or isolation validation failed")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
