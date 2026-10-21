"""One explicit low-frequency public batch. Four boards <=20, each unique series <=15 comments."""

import argparse
import fcntl
import json
import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.hongguo import CaptureHongguo, submit
from app.connectors.hongguo import BOARDS, VERSION, Hongguo
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.service import shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--comments-only",
        action="store_true",
        help="Collect comments only for already sealed same-day Hongguo boards; no ranking requests",
    )
    parser.add_argument(
        "--repair-storage",
        action="store_true",
        help="Explicit one-time repair of the initial NUL storage failure only; never automatic",
    )
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "boards": list(BOARDS),
                    "per_board": 20,
                    "comments_per_series": 15,
                    "max_requests": 84,
                    "interval_seconds": 10,
                    "retries": 0,
                    "model_calls": 0,
                }
            )
        )
        return
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    directory = ROOT / "data/hongguo"
    directory.mkdir(parents=True, exist_ok=True)
    lock = os.fdopen(
        os.open(directory / "batch.lock", os.O_CREAT | os.O_RDWR, 0o600), "w"
    )
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = directory / f"batch-{shanghai_date()}.json"
    record = (
        json.loads(path.read_text())
        if path.exists()
        else {"date": str(shanghai_date()), "status": "running", "jobs": []}
    )

    record["status"] = "running"

    def save():
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    engine = application_engine()
    handler = CaptureHongguo(Hongguo())
    runner = Runner(engine, {("collect.hongguo", VERSION): handler}, lease_seconds=120)
    with engine.begin() as c:
        _, context = enter(c)
        p = MemberPrincipal(context["org_id"], context["member_id"])

    def run(request, **kwargs):
        if str(shanghai_date()) != record["date"]:
            raise RuntimeError("Date changed; stopped without requesting")
        with engine.begin() as c:
            saved = submit(c, p, request, handler, **kwargs)
        try:
            with engine.connect() as c:
                state = c.exec_driver_sql(
                    "SELECT state FROM tasks WHERE org_id=%s AND id=%s",
                    (p.org_id, UUID(saved["task_id"])),
                ).scalar_one()
            if state == "queued":
                runner.run(p.org_id, UUID(saved["task_id"]))
            with engine.begin() as c:
                state = c.exec_driver_sql(
                    "SELECT state FROM tasks WHERE org_id=%s AND id=%s",
                    (p.org_id, UUID(saved["task_id"])),
                ).scalar_one()
                count = c.exec_driver_sql(
                    "SELECT count(*) FROM collection_calls WHERE org_id=%s AND job_id=%s",
                    (p.org_id, UUID(saved["job_id"])),
                ).scalar_one()
                if (
                    state == "failed"
                    and c.exec_driver_sql(
                        "SELECT EXISTS(SELECT 1 FROM intelligence_snapshots WHERE org_id=%s AND job_id=%s AND sealed_at IS NOT NULL)",
                        (p.org_id, UUID(saved["job_id"])),
                    ).scalar_one()
                ):
                    state = "recovered"
            item = {**saved, "request": request, "state": state, "calls": count}
            record["jobs"] = [
                x for x in record["jobs"] if x["task_id"] != saved["task_id"]
            ] + [item]
            save()
            print(
                json.dumps(
                    {"request": request, "state": state, "jobs": len(record["jobs"])},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if state not in ("succeeded", "recovered"):
                raise RuntimeError("Capture stopped; no automatic retry")
        finally:
            with engine.begin() as c:
                current = (
                    c.exec_driver_sql(
                        "SELECT lock_version,enabled FROM sources WHERE org_id=%s AND id=%s",
                        (p.org_id, UUID(saved["source_id"])),
                    )
                    .mappings()
                    .one()
                )
                if current["enabled"]:
                    compare_and_swap(
                        c,
                        "sources",
                        p.org_id,
                        UUID(saved["source_id"]),
                        current["lock_version"],
                        {"enabled": False},
                    )

    try:
        save()
        for board in BOARDS:
            if args.comments_only:
                continue
            run(
                {"board": board},
                storage_repair=args.repair_storage and board == "hot-drama",
            )
        with engine.begin() as c:
            members = (
                c.exec_driver_sql(
                    "SELECT DISTINCT ON (o.content_id) o.content_id,x.platform_content_id,s.id snapshot_id FROM intelligence_snapshots s JOIN sources src ON src.org_id=s.org_id AND src.id=s.source_id JOIN snapshot_entries e ON e.org_id=s.org_id AND e.snapshot_id=s.id JOIN content_observations o ON o.org_id=e.org_id AND o.id=e.content_observation_id JOIN external_contents x ON x.org_id=o.org_id AND x.id=o.content_id WHERE s.org_id=%s AND src.platform_code='hongguo' AND s.business_code='motion_comic' AND s.business_date=%s AND s.sealed_at IS NOT NULL ORDER BY o.content_id,s.created_at DESC",
                    (p.org_id, shanghai_date()),
                )
                .mappings()
                .all()
            )
        if len(members) > 80:
            raise RuntimeError("Too many unique series")
        record["unique_series"] = len(members)
        save()
        for item in members:
            run(
                {"series_id": item["platform_content_id"]},
                snapshot_id=item["snapshot_id"],
                content_id=item["content_id"],
            )
        record["status"] = "completed"
    except BaseException:
        record["status"] = "stopped"
        raise
    finally:
        save()
        engine.dispose()
        lock.close()


if __name__ == "__main__":
    main()
