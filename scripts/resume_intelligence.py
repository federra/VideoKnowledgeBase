"""Explicit authorized same-day continuation; no successful requests are repeated."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.database import application_engine
from app.intelligence.refresh_resume import runner, start_resume
from app.security.sessions import MemberPrincipal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=UUID, required=True)
    args = parser.parse_args()
    engine = application_engine()
    with engine.begin() as c:
        org, member = c.exec_driver_sql(
            "SELECT m.org_id,m.id FROM members m JOIN organizations o ON o.id=m.org_id WHERE o.name='本地单人工作区' AND m.login_name='__local_owner__' AND m.disabled_at IS NULL"
        ).one()
        tid = start_resume(c, MemberPrincipal(org, member), args.batch)
    print(
        json.dumps({"resume_task": str(tid), "original_batch": str(args.batch)}),
        flush=True,
    )
    result = runner(engine).run(org, tid)
    print(json.dumps({"state": result}), flush=True)
    if result != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
