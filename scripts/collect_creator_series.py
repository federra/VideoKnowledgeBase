"""Explicit local CLI: monitored creators only; never refresh paid board channels."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import application_engine
from app.intelligence.creator_contracts import CreatorBatch
from app.intelligence.creators import save
from app.intelligence.refresh import latest, start
from app.intelligence.refresh_worker import runtime
from app.security.sessions import MemberPrincipal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--business",
        default="motion_comic",
        choices=["motion_comic", "story_short", "ecommerce_video"],
    )
    parser.add_argument(
        "--links",
        type=Path,
        help="Optional canonical Douyin homepage URLs, one per line",
    )
    parser.add_argument(
        "--reparse-failed-batch",
        type=UUID,
        help="Zero HTTP recovery of this saved failed creator batch",
    )
    args = parser.parse_args()
    engine = application_engine()
    with engine.begin() as c:
        member = c.exec_driver_sql(
            "SELECT m.org_id,m.id FROM members m JOIN organizations o ON o.id=m.org_id WHERE o.name='本地单人工作区' AND m.login_name='__local_owner__' AND m.disabled_at IS NULL"
        ).one()
        p = MemberPrincipal(member.org_id, member.id)
        if args.reparse_failed_batch:
            if args.links:
                raise ValueError("Reparse does not accept new URLs")
        elif args.links:
            saved = save(
                c,
                p,
                CreatorBatch(business_code=args.business, links=args.links.read_text()),
                str(uuid4()),
            )
            if any(r["state"] not in ("added", "duplicate") for r in saved["results"]):
                raise ValueError("Invalid creator configuration; review the local file")
        batch = (
            None
            if args.reparse_failed_batch
            else start(c, p, args.business, str(uuid4()), creators_only=True)
        )
    if args.reparse_failed_batch:
        from app.collection.creator_reparse import reparse_batch

        ids = reparse_batch(engine, p, args.reparse_failed_batch)
        print(json.dumps({"reparsed": len(ids), "external_calls": 0}))
        return
    print(
        json.dumps(
            {"batch": batch["task_id"], "scope": "creators_only", "paid_calls": 0}
        ),
        flush=True,
    )
    state = runtime(engine).run(p.org_id, UUID(batch["task_id"]))
    with engine.begin() as c:
        status = latest(c, p, args.business, UUID(batch["task_id"]))
        print(
            json.dumps(
                {"state": state, "channels": status["channels"]},
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
