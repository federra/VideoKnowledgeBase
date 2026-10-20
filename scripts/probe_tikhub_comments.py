"""One authorized first-page comment capture. Never paginates, retries or invokes AI."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.comments import Capture, submit_capture
from app.connectors.tikhub import VERSION, TikHub
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.service import feed, shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def plan():
    return {
        "provider": "tikhub",
        "business": "motion_comic",
        "max_requests": 1,
        "cursor": 0,
        "count": 20,
        "normalization": "pending_actual_response",
        "ai_calls": 0,
        "key_configured": bool(
            settings.tikhub_api_key and settings.tikhub_api_key.get_secret_value().strip()
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(plan(), ensure_ascii=False))
        return
    if not settings.local_single_user:
        raise RuntimeError("Explicit local workspace required")
    connector = TikHub(
        lambda: settings.tikhub_api_key.get_secret_value() if settings.tikhub_api_key else None
    )
    connector.ready()  # Missing key cannot create task/source/journal or reserve a request.
    day = shanghai_date()
    marker = ROOT / f"data/tikhub/live-comment-probe-{day}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    record = {
        **plan(),
        "requested_at": datetime.now(UTC).isoformat(),
        "business_date": str(day),
        "status": "reserved",
        "key": str(uuid4()),
    }
    with os.fdopen(fd, "w") as file:
        json.dump(record, file, ensure_ascii=False)
    engine = application_engine()
    org = None
    source = None
    try:
        with engine.begin() as c:
            _, context = enter(c)
            org = context["org_id"]
            p = MemberPrincipal(org, context["member_id"])
            current = feed(c, p, "motion_comic", day, "creator", 1)
            works = [
                v
                for v in current["items"]
                if v["entry"]["observation"]["comment_count"] is not None
                and int(v["entry"]["observation"]["comment_count"]) > 0
            ]
            if not works:
                raise RuntimeError("No authorized same-day work with known positive comment count")
            selected = max(works, key=lambda v: int(v["entry"]["observation"]["comment_count"]))
            handler = Capture(connector)
            accepted = submit_capture(
                c,
                p,
                UUID(selected["entry"]["id"])
                if isinstance(selected["entry"]["id"], str)
                else selected["entry"]["id"],
                record["key"],
                handler,
            )
            record.update(accepted)
            source = UUID(accepted["source_id"])
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        state = Runner(engine, {("collect.tikhub-comments", VERSION): handler}).run(
            org, UUID(accepted["task_id"])
        )
        with engine.connect() as c:
            raw = (
                c.exec_driver_sql(
                    "SELECT a.id,a.body_text FROM raw_assets a JOIN collection_jobs j ON j.id=a.collection_job_id AND j.org_id=a.org_id WHERE j.org_id=%s AND j.task_id=%s ORDER BY a.created_at DESC LIMIT 1",
                    (org, UUID(accepted["task_id"])),
                )
                .mappings()
                .one_or_none()
            )
            count = c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls cc JOIN collection_jobs j ON j.id=cc.job_id WHERE j.org_id=%s AND j.task_id=%s",
                (org, UUID(accepted["task_id"])),
            ).scalar_one()
            error = c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE org_id=%s AND id=%s",
                (org, UUID(accepted["task_id"])),
            ).scalar_one()
        record.update(status=state, external_request_reservations=count, safe_error_code=error)
        if raw:
            record["raw_asset_id"] = str(raw["id"])
            try:
                envelope = json.loads(raw["body_text"])
                data = envelope.get("data") if isinstance(envelope, dict) else None
                record["data_type"] = type(data).__name__
                record["data_keys"] = sorted(data.keys()) if isinstance(data, dict) else []
            except (ValueError, TypeError):
                record["data_type"] = "unparsed"
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in record.items() if k != "key"}, ensure_ascii=False))
    finally:
        if org and source:
            with engine.begin() as c:
                version = c.exec_driver_sql(
                    "SELECT lock_version FROM sources WHERE org_id=%s AND id=%s", (org, source)
                ).scalar_one()
                compare_and_swap(c, "sources", org, source, version, {"enabled": False})
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except FileExistsError:
        print(
            "A request intent already exists for today; inspect it without reissuing.",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 - provider URL/body and credentials never printed
        print("Comment capture stopped: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
