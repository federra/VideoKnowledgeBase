"""Explicit Qimao-only batch: 10 fixed first pages, <=20 books/page, >=10s interval."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.novels import submit
from app.collection.qimao import QimaoCollect
from app.connectors.novels import VERSION
from app.connectors.qimao import Qimao, boards
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.service import shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def validate_resume(record, day):
    if record.get("date") != str(day):
        raise RuntimeError("Cannot resume another date")
    if record.get("status") == "blocked" or any(
        call.get("http_status") in (403, 429)
        for job in record.get("jobs", [])
        for call in job.get("calls", [])
    ):
        raise RuntimeError("Batch stopped after source refusal; resume is not allowed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing same-day tasks; never retry failed requests",
    )
    parser.add_argument("--refresh-existing", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "platform": "qimao",
                    "boards": 10,
                    "max_items": 20,
                    "min_interval": 10,
                    "retries": 0,
                    "paid_calls": 0,
                }
            )
        )
        return
    if not settings.local_single_user:
        raise RuntimeError("Local single-user workspace required")
    directory = ROOT / "data/qimao"
    directory.mkdir(parents=True, exist_ok=True)
    day = shanghai_date()
    marker = directory / f"batch-{day}.json"
    if args.resume:
        record = json.loads(marker.read_text())
        validate_resume(record, day)
    else:
        record = {"date": str(day), "status": "running", "jobs": []}
        with os.fdopen(
            os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as f:
            json.dump(record, f)

    def save():
        tmp = marker.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(marker)

    engine = application_engine()
    handler = QimaoCollect(Qimao())
    runner = Runner(engine, {("collect.novels", VERSION): handler})
    try:
        with engine.begin() as c:
            _, ctx = enter(c)
            p = MemberPrincipal(ctx["org_id"], ctx["member_id"])
        for index, board in enumerate(boards()):
            if any(j["board"] == board["code"] for j in record["jobs"]):
                continue
            if shanghai_date() != day:
                raise RuntimeError("Date changed; stopped")
            if index:
                time.sleep(10)
            ticket = None
            try:
                with engine.begin() as c:
                    ticket = submit(
                        c, p, board, handler, refresh_existing=args.refresh_existing
                    )
                    state = c.exec_driver_sql(
                        "SELECT state FROM tasks WHERE org_id=%s AND id=%s",
                        (p.org_id, UUID(ticket["task_id"])),
                    ).scalar_one()
                if state == "queued":
                    runner.run(p.org_id, UUID(ticket["task_id"]))
                with engine.begin() as c:
                    task = (
                        c.exec_driver_sql(
                            "SELECT state,safe_error_code FROM tasks WHERE org_id=%s AND id=%s",
                            (p.org_id, UUID(ticket["task_id"])),
                        )
                        .mappings()
                        .one()
                    )
                    calls = [
                        dict(x)
                        for x in c.exec_driver_sql(
                            "SELECT http_status,outcome,returned_items FROM collection_calls WHERE org_id=%s AND job_id=%s",
                            (p.org_id, UUID(ticket["job_id"])),
                        ).mappings()
                    ]
                    count = c.exec_driver_sql(
                        "SELECT coalesce(sum(entry_count),0) FROM intelligence_snapshots WHERE org_id=%s AND job_id=%s",
                        (p.org_id, UUID(ticket["job_id"])),
                    ).scalar_one()
                result = dict(
                    **ticket, board=board["code"], **task, calls=calls, saved=int(count)
                )
                record["jobs"].append(result)
                save()
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if any(x["http_status"] in (403, 429) for x in calls):
                    record["status"] = "blocked"
                    save()
                    break
            finally:
                if ticket:
                    with engine.begin() as c:
                        src = (
                            c.exec_driver_sql(
                                "SELECT lock_version,enabled FROM sources WHERE org_id=%s AND id=%s",
                                (p.org_id, UUID(ticket["source_id"])),
                            )
                            .mappings()
                            .one()
                        )
                        if src["enabled"]:
                            compare_and_swap(
                                c,
                                "sources",
                                p.org_id,
                                UUID(ticket["source_id"]),
                                src["lock_version"],
                                {"enabled": False},
                            )
        else:
            record["status"] = (
                "finished"
                if all(j["state"] == "succeeded" for j in record["jobs"])
                else "partial"
            )
            save()
    except BaseException:
        record["status"] = "stopped"
        save()
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
