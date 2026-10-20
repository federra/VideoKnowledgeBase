"""Explicit Qidian-only mobile SSR batch. Never fetches or changes Fanqie."""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.novels import submit
from app.collection.qidian_mobile import QidianCollect
from app.connectors.novels import VERSION
from app.connectors.qidian_mobile import METHOD, QidianMobile, discover
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.service import shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def fanqie_fingerprint(c, org):
    source = "SELECT id FROM sources WHERE org_id=%s AND platform_code='fanqie'"
    job = (
        "SELECT id FROM collection_jobs WHERE org_id=%s AND source_id IN ("
        + source
        + ")"
    )
    snap = (
        "SELECT id FROM intelligence_snapshots WHERE org_id=%s AND source_id IN ("
        + source
        + ")"
    )
    contents = (
        "SELECT id FROM external_contents WHERE org_id=%s AND platform_code='fanqie'"
    )
    specs = {
        "sources": ("id IN (" + source + ")", (org,)),
        "tasks": ("source_id IN (" + source + ")", (org,)),
        "collection_jobs": ("source_id IN (" + source + ")", (org,)),
        "collection_calls": ("job_id IN (" + job + ")", (org, org)),
        "raw_assets": ("collection_job_id IN (" + job + ")", (org, org)),
        "intelligence_snapshots": ("source_id IN (" + source + ")", (org,)),
        "snapshot_entries": ("snapshot_id IN (" + snap + ")", (org, org)),
        "external_contents": ("platform_code='fanqie'", ()),
        "content_observations": ("content_id IN (" + contents + ")", (org,)),
    }
    result = {}
    for table, (where, args) in specs.items():
        rows = (
            c.exec_driver_sql(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE t.org_id=%s AND ({where}) ORDER BY t.id",
                (org, *args),
            )
            .scalars()
            .all()
        )
        result[table] = {
            "count": len(rows),
            "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest(),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "platform": "qidian",
                    "method": METHOD,
                    "max_items_per_board": 30,
                    "page": 1,
                    "retries": 0,
                    "fanqie_requests": 0,
                    "model_calls": 0,
                }
            )
        )
        return
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    directory = ROOT / "data/qidian"
    directory.mkdir(parents=True, exist_ok=True)
    day = shanghai_date()
    marker = directory / f"mobile-batch-{day}.json"
    record = {
        "date": str(day),
        "status": "reserved",
        "method": METHOD,
        "jobs": [],
        "model_calls": 0,
        "fanqie_requests": 0,
    }
    if args.resume:
        record = json.loads(marker.read_text())
        if record["date"] != str(day) or record["status"] != "stopped":
            raise RuntimeError("Only stopped current batch can resume")
    else:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)

    def save():
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

    engine = application_engine()
    handler = QidianCollect(QidianMobile())
    runner = Runner(engine, {("collect.novels", VERSION): handler})
    try:
        with engine.begin() as c:
            _, context = enter(c)
            p = MemberPrincipal(context["org_id"], context["member_id"])
            before = fanqie_fingerprint(c, p.org_id)
        if "fanqie_before" not in record:
            record["fanqie_before"] = before
            save()
        elif before != record["fanqie_before"]:
            raise RuntimeError("Fanqie changed since stopped batch")

        def run(board):
            saved = None
            try:
                with engine.begin() as c:
                    saved = submit(c, p, board, handler)
                    state = c.exec_driver_sql(
                        "SELECT state FROM tasks WHERE org_id=%s AND id=%s",
                        (p.org_id, UUID(saved["task_id"])),
                    ).scalar_one()
                if state == "queued":
                    runner.run(p.org_id, UUID(saved["task_id"]))
                with engine.begin() as c:
                    task = (
                        c.exec_driver_sql(
                            "SELECT state,safe_error_code FROM tasks WHERE org_id=%s AND id=%s",
                            (p.org_id, UUID(saved["task_id"])),
                        )
                        .mappings()
                        .one()
                    )
                    raw = c.exec_driver_sql(
                        "SELECT body_text FROM raw_assets WHERE org_id=%s AND collection_job_id=%s",
                        (p.org_id, UUID(saved["job_id"])),
                    ).scalar_one_or_none()
                    calls = (
                        c.exec_driver_sql(
                            "SELECT http_status,outcome,returned_items FROM collection_calls WHERE org_id=%s AND job_id=%s",
                            (p.org_id, UUID(saved["job_id"])),
                        )
                        .mappings()
                        .all()
                    )
                    count = c.exec_driver_sql(
                        "SELECT coalesce(sum(entry_count),0) FROM intelligence_snapshots WHERE org_id=%s AND job_id=%s",
                        (p.org_id, UUID(saved["job_id"])),
                    ).scalar_one()
                record["jobs"] = [
                    j for j in record["jobs"] if j["board"] != board["code"]
                ]
                record["jobs"].append(
                    {
                        **saved,
                        "board": board["code"],
                        "name": board.get("name"),
                        "state": task["state"],
                        "safe_error_code": task["safe_error_code"],
                        "saved": int(count),
                        "calls": [dict(v) for v in calls],
                    }
                )
                save()
                print(json.dumps(record["jobs"][-1], ensure_ascii=False), flush=True)
                return raw if task["state"] == "succeeded" else None
            finally:
                if saved:
                    with engine.begin() as c:
                        value = (
                            c.exec_driver_sql(
                                "SELECT lock_version,enabled FROM sources WHERE org_id=%s AND id=%s",
                                (p.org_id, UUID(saved["source_id"])),
                            )
                            .mappings()
                            .one()
                        )
                        if value["enabled"]:
                            compare_and_swap(
                                c,
                                "sources",
                                p.org_id,
                                UUID(saved["source_id"]),
                                value["lock_version"],
                                {"enabled": False},
                            )
                time.sleep(2.1)

        boards = []
        for gender in ("male", "female"):
            html = run(
                {
                    "platform": "qidian",
                    "method": METHOD,
                    "rank_type": "catalog",
                    "gender": gender,
                    "code": f"qidian:mobile:{gender}:catalog",
                    "name": ("男频" if gender == "male" else "女频") + "官方目录",
                }
            )
            if html:
                boards.extend(discover(html, gender))
        for board in boards:
            run(board)
        with engine.begin() as c:
            after = fanqie_fingerprint(c, p.org_id)
        record.update(
            fanqie_after=after,
            fanqie_unchanged=record["fanqie_before"] == after,
            status="finished",
            sources_paused=True,
            discovered_board_count=len(boards),
        )
        save()
        if not record["fanqie_unchanged"]:
            raise RuntimeError("Fanqie fingerprint changed")
    except Exception as exc:
        record.update(status="stopped", error_type=type(exc).__name__)
        save()
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
