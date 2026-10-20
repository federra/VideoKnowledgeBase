"""Project a sealed feedback version into a same-day insight; no external calls."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import settings
from app.core.database import application_engine
from app.intelligence.insight import InsightTask, latest_insight, submit_insight
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feedback_id", type=UUID)
    args = parser.parse_args()
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    engine = application_engine()
    try:
        handler = InsightTask()
        with engine.begin() as c:
            _, context = enter(c)
            p = MemberPrincipal(context["org_id"], context["member_id"])
            tid = submit_insight(c, p, args.feedback_id, handler)
        Runner(engine, {("intelligence.insight", "1"): handler}).run(p.org_id, tid)
        with engine.begin() as c:
            state = c.exec_driver_sql(
                "SELECT state FROM tasks WHERE org_id=%s AND id=%s", (p.org_id, tid)
            ).scalar_one()
            scope = c.exec_driver_sql(
                "SELECT s.business_code,s.business_date FROM feedback_snapshots f JOIN intelligence_snapshots s ON s.org_id=f.org_id AND s.id=f.snapshot_id WHERE f.org_id=%s AND f.id=%s",
                (p.org_id, args.feedback_id),
            ).one()
            report = latest_insight(c, p, *scope)
        if state != "succeeded" or not report:
            raise RuntimeError("Insight failed")
        print(
            json.dumps(
                {
                    "task_id": str(tid),
                    "state": state,
                    "insight_id": str(report["id"]),
                    "feedback_id": str(args.feedback_id),
                    "sample_count": report["sample_count"],
                    "classified_count": report["classified_count"],
                    "external_calls_added": 0,
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - CLI never prints private database payloads
        print("Insight projection stopped: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
