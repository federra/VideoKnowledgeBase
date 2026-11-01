"""User-authorized one-off genre explanations; dry-run by default, no new model setting."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.database import application_engine
from app.knowledge.genre_explanations import KIND, VERSION, Explain, load, start
from app.security.authorization import Authorizer
from app.security.local import owner_identity
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner

REASON = "2026-10-31 用户要求直接调用现有模型为每条题材生成一句解释并导入；不增加模型配置或页面操作。"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    engine = application_engine()
    with engine.begin() as c:
        member = owner_identity(c)
        p = MemberPrincipal(member.org_id, member.id)
        ids = (
            c.exec_driver_sql(
                "SELECT r.id FROM knowledge_items k JOIN knowledge_publications pub ON pub.org_id=k.org_id AND pub.id=k.published_publication_id JOIN knowledge_revisions r ON r.org_id=pub.org_id AND r.id=pub.revision_id WHERE k.org_id=%s AND k.recycled_at IS NULL AND r.browse_category='genre' AND coalesce(btrim(r.explanation),'')='' ORDER BY r.id",
                (p.org_id,),
            )
            .scalars()
            .all()
        )
        existing = load(c, p, ids, Authorizer(c, p))
    ids = [rid for rid in ids if rid not in existing]
    print(
        json.dumps(
            {
                "genres": len(ids) + len(existing),
                "existing": len(existing),
                "max_new_calls": (len(ids) + 19) // 20,
                "execute": args.execute,
            }
        ),
        flush=True,
    )
    if not args.execute:
        return
    runner = Runner(engine, {(KIND, VERSION): Explain()}, lease_seconds=720)
    for i in range(0, len(ids), 20):
        batch = ids[i : i + 20]
        with engine.begin() as c:
            task = start(c, p, batch, REASON)
        tid = UUID(task["id"])
        with engine.connect() as c:
            state = c.exec_driver_sql(
                "SELECT state FROM tasks WHERE org_id=%s AND id=%s", (p.org_id, tid)
            ).scalar_one()
        print(
            json.dumps({"batch": i // 20 + 1, "task": str(tid), "state": state}),
            flush=True,
        )
        if state == "queued":
            runner.run(p.org_id, tid)
        with engine.connect() as c:
            state = c.exec_driver_sql(
                "SELECT state FROM tasks WHERE org_id=%s AND id=%s", (p.org_id, tid)
            ).scalar_one()
            calls = c.exec_driver_sql(
                "SELECT count(*) FROM ai_executions WHERE org_id=%s AND task_id=%s",
                (p.org_id, tid),
            ).scalar_one()
        print(
            json.dumps(
                {"batch": i // 20 + 1, "task": str(tid), "state": state, "calls": calls}
            ),
            flush=True,
        )
        assert calls <= 1
    engine.dispose()


if __name__ == "__main__":
    main()
