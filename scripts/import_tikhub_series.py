"""Offline normalization of a previously captured series response: zero external calls."""

import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.series import NormalizeSeries, submit_normalization
from app.connectors.tikhub_series import VERSION
from app.core.database import application_engine
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def main():
    raw = UUID(sys.argv[1])
    engine = application_engine()
    with engine.begin() as c:
        _, ctx = enter(c)
        p = MemberPrincipal(ctx["org_id"], ctx["member_id"])
        tid = submit_normalization(c, p, raw)
    result = Runner(engine, {("series.normalize", VERSION): NormalizeSeries()}).run(
        p.org_id, tid
    )
    print(json.dumps({"task_id": str(tid), "state": result, "external_calls": 0}))
    engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - safe error only
        print("Series import failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
