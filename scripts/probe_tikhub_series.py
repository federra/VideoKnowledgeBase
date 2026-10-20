"""One durable first-page series probe; no pagination/retry/model requests."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.series import CaptureSeries, submit_capture
from app.connectors.tikhub_series import REQUEST, VERSION, Series
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
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"request": REQUEST, "external_calls": 0}))
        return
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    api = Series(
        lambda: (
            settings.tikhub_api_key.get_secret_value()
            if settings.tikhub_api_key
            else None
        )
    )
    api.ready()
    marker = ROOT / f"data/tikhub/live-series-probe-{shanghai_date()}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "status": "reserved",
        "business_date": str(shanghai_date()),
        "request": REQUEST,
        "key": str(uuid4()),
    }
    with os.fdopen(
        os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
    ) as f:
        json.dump(record, f)
    engine = application_engine()
    source = None
    p = None
    try:
        handler = CaptureSeries(api, min_interval=0)
        with engine.begin() as c:
            _, ctx = enter(c)
            p = MemberPrincipal(ctx["org_id"], ctx["member_id"])
            accepted = submit_capture(c, p, record["key"], handler)
        record.update(accepted)
        source = UUID(record["source_id"])
        marker.write_text(json.dumps(record) + "\n")
        record["status"] = Runner(
            engine, {("collect.tikhub-series", VERSION): handler}
        ).run(p.org_id, UUID(record["task_id"]))
        with engine.connect() as c:
            record["calls"] = c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE job_id=%s",
                (UUID(record["job_id"]),),
            ).scalar_one()
            raws = (
                c.exec_driver_sql(
                    "SELECT id,sha256 FROM raw_assets WHERE collection_job_id=%s",
                    (UUID(record["job_id"]),),
                )
                .mappings()
                .all()
            )
            record["raw_assets"] = [
                {"id": str(r["id"]), "sha256": r["sha256"]} for r in raws
            ]
    finally:
        if source and p:
            with engine.begin() as c:
                version = c.exec_driver_sql(
                    "SELECT lock_version FROM sources WHERE org_id=%s AND id=%s",
                    (p.org_id, source),
                ).scalar_one()
                compare_and_swap(
                    c, "sources", p.org_id, source, version, {"enabled": False}
                )
            record["source_paused"] = True
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        engine.dispose()
    print(
        json.dumps({k: v for k, v in record.items() if k != "key"}, ensure_ascii=False)
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - never stringify credential-bearing failures
        print(
            "Series probe stopped: " + type(exc).__name__ + "; do not repeat.",
            file=sys.stderr,
        )
        sys.exit(1)
