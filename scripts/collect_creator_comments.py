"""Explicit free dedicated-browser first-episode comment collection; no paid providers."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.creator_browser_comments import BrowserComments, run
from app.core.database import application_engine
from app.security.sessions import MemberPrincipal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=UUID, action="append", required=True)
    parser.add_argument("--limit", type=int, default=10, choices=range(1, 11))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--offset", type=int, default=0, choices=range(10))
    args = parser.parse_args()
    engine = application_engine()
    with engine.begin() as c:
        m = c.exec_driver_sql(
            "SELECT m.org_id,m.id FROM members m JOIN organizations o ON o.id=m.org_id WHERE o.name='本地单人工作区' AND m.login_name='__local_owner__' AND m.disabled_at IS NULL"
        ).one()
        p = MemberPrincipal(m.org_id, m.id)
    result = run(
        engine,
        p,
        args.snapshot,
        limit=args.limit,
        offset=args.offset,
        handler=BrowserComments(headed=args.headed),
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
