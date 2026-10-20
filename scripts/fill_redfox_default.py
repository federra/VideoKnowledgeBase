"""One controlled default-relevance video search; at most ten stored works, no retries."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.service import configure_connection, configure_source, submit
from app.connectors.redfox import KEYWORD_DEFAULT, VERSION
from app.contracts.models import CollectionCreate
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.service import feed, shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.handlers import registry
from app.tasks.service import Runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "keyword": "漫剧",
                    "offset": 0,
                    "sortType": "_0",
                    "max_requests": 1,
                    "max_saved_works": 10,
                    "paid_call": False,
                },
                ensure_ascii=False,
            )
        )
        return
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    handlers = registry()
    handlers[("collect.redfox", VERSION)].connector.ready()
    directory = ROOT / "data/redfox"
    directory.mkdir(parents=True, exist_ok=True)
    day = shanghai_date()
    marker = directory / f"live-default-fill-{day}.json"
    record = {
        "status": "reserved",
        "business_date": str(day),
        "max_requests": 1,
        "max_items": 10,
        "idempotency_key": str(uuid4()),
    }
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(record, f)
    engine = application_engine()
    source = None
    p = None
    try:
        with engine.begin() as c:
            _, context = enter(c)
            p = MemberPrincipal(context["org_id"], context["member_id"])
            connection = configure_connection(c, p, "红狐")
            source = configure_source(
                c, p, "漫剧关键词 · 默认相关性排序", "keyword", "漫剧", enabled=True
            )
            accepted = submit(
                c,
                p,
                CollectionCreate(
                    source_id=source,
                    provider_connection_id=connection,
                    capability_code=KEYWORD_DEFAULT,
                    max_items=10,
                ),
                record["idempotency_key"],
                handlers[("collect.redfox", VERSION)],
            )
            tid = UUID(accepted["task"]["task_id"])
        record.update(status="submitted", task_id=str(tid), source_id=str(source))
        marker.write_text(json.dumps(record, ensure_ascii=False) + "\n")
        Runner(engine, handlers).run(p.org_id, tid)
        with engine.begin() as c:
            task = (
                c.exec_driver_sql(
                    "SELECT state,safe_error_code FROM tasks WHERE org_id=%s AND id=%s",
                    (p.org_id, tid),
                )
                .mappings()
                .one()
            )
            job = c.exec_driver_sql(
                "SELECT id FROM collection_jobs WHERE org_id=%s AND task_id=%s",
                (p.org_id, tid),
            ).scalar_one()
            calls = c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s AND job_id=%s",
                (p.org_id, job),
            ).scalar_one()
            snaps = (
                c.exec_driver_sql(
                    "SELECT id,entry_count FROM intelligence_snapshots WHERE org_id=%s AND job_id=%s",
                    (p.org_id, job),
                )
                .mappings()
                .all()
            )
            result = feed(c, p, "motion_comic", day, "board")
            record.update(
                status=task["state"],
                safe_error_code=task["safe_error_code"],
                job_id=str(job),
                external_request_reservations=calls,
                snapshot_ids=[str(s["id"]) for s in snaps],
                saved_works=sum(s["entry_count"] for s in snaps),
                board_total=result["total"],
                ranking_status=result["keyword_ranking_status"],
                model_calls_added=0,
            )
            if task["state"] != "succeeded" or calls != 1:
                raise RuntimeError("Inspect saved task; no retry")
    finally:
        if source is not None and p is not None:
            with engine.begin() as c:
                current = c.exec_driver_sql(
                    "SELECT lock_version FROM sources WHERE org_id=%s AND id=%s",
                    (p.org_id, source),
                ).scalar_one()
                compare_and_swap(
                    c, "sources", p.org_id, source, current, {"enabled": False}
                )
            record["source_paused"] = True
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        engine.dispose()
    print(
        json.dumps(
            {k: v for k, v in record.items() if k != "idempotency_key"},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - do not log keys, raw provider bodies or SQL parameters
        print(
            "Default fill stopped: "
            + type(exc).__name__
            + "; do not repeat the request.",
            file=sys.stderr,
        )
        sys.exit(1)
