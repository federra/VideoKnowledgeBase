"""S07.1: one authorized synopsis / one model request; no collection or publication."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.research import freeze_input
from app.ai.research_probe import KIND, Probe, sample, submit_probe
from app.collection.service import insert
from app.core.config import settings
from app.core.database import application_engine
from app.intelligence.service import feed, shanghai_date
from app.security.authorization import Authorizer
from app.security.governance import delegate, org_action, revoke, set_role_actions
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.security.storage import audit, lock_org
from app.tasks.service import Runner


def temporary_run_grant(c, p, source_id, key):
    """Explicit user-authorized single-source grant; caller must revoke in finally."""
    lock_org(c, p.org_id)
    org_action(c, p, "role.manage")
    code = "s071_probe_runner"
    role = c.exec_driver_sql(
        "SELECT id FROM role_definitions WHERE org_id=%s AND code=%s", (p.org_id, code)
    ).scalar_one_or_none()
    if role is None:
        role = insert(
            c, "role_definitions", p.org_id, code=code, name="S07.1单来源临时执行"
        )
        set_role_actions(c, p, uuid5(p.org_id, key + ":role"), role, ["research.run"])
        audit(
            c, p.org_id, p.member_id, "role.create", "role", role, uuid5(p.org_id, key)
        )
    else:
        actions = set(
            c.exec_driver_sql(
                "SELECT action_code FROM role_actions WHERE org_id=%s AND role_id=%s",
                (p.org_id, role),
            ).scalars()
        )
        if actions != {"research.run"}:
            raise RuntimeError("Temporary role differs from approved scope")
    return delegate(c, p, uuid5(p.org_id, key), p.member_id, role, "source", source_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-model", action="store_true")
    parser.add_argument(
        "--temporary-run-grant",
        action="store_true",
        help="Requires explicit human approval; single source, revoked in finally",
    )
    args = parser.parse_args()
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    engine = application_engine()
    grant_id = None
    marker = None
    result = None
    try:
        with engine.begin() as c:
            _, ctx = enter(c)
            p = MemberPrincipal(ctx["org_id"], ctx["member_id"])
            data = feed(c, p, "motion_comic", shanghai_date())
            if data["keyword_ranking_status"] != "series_order" or not data["items"]:
                raise RuntimeError("No authorized series snapshot")
            entry = data["items"][0]["entry"]
            snapshot_id, entry_id = (
                UUID(str(entry["snapshot_id"])),
                UUID(str(entry["id"])),
            )
            value, snap, _ = sample(c, p, snapshot_id, entry_id)
            Authorizer(c, p).require("sources", snap["source_id"], "research.submit")
            if args.execute_model and not args.temporary_run_grant:
                Authorizer(c, p).require("sources", snap["source_id"], "research.run")
        result = {
            "definition_version": "research.decompose.v1",
            "snapshot_id": str(snapshot_id),
            "entry_id": str(entry_id),
            "input_sha256": freeze_input("decompose", value)["sha256"],
            "input_characters": sum(len(x.text) for x in value.segments),
            "scope": value.scope,
            "collection_calls_added": 0,
            "model_calls_added": 0,
            "business_publications": 0,
        }
        if args.execute_model:
            if (
                not settings.deepseek_key
                or not settings.deepseek_key.get_secret_value().strip()
            ):
                raise RuntimeError("Model key missing")
            marker = ROOT / "data/deepseek/s071-definition-probe.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"state": "reserved", **result}, f)
            handler = Probe()
            with engine.begin() as c:
                if args.temporary_run_grant:
                    grant_id = temporary_run_grant(
                        c, p, snap["source_id"], "s071:" + str(entry_id)
                    )
                tid = submit_probe(c, p, snapshot_id, entry_id, handler)
            marker.write_text(
                json.dumps(
                    {
                        "state": "submitted",
                        "task_id": str(tid),
                        "temporary_grant_id": str(grant_id) if grant_id else None,
                        **result,
                    }
                )
                + "\n"
            )
            state = Runner(engine, {(KIND, "1"): handler}).run(p.org_id, tid)
            with engine.connect() as c:
                executions = (
                    c.exec_driver_sql(
                        "SELECT id,result_state,input_tokens,output_tokens,safe_error_code FROM ai_executions WHERE org_id=%s AND task_id=%s",
                        (p.org_id, tid),
                    )
                    .mappings()
                    .all()
                )
                error = c.exec_driver_sql(
                    "SELECT safe_error_code FROM tasks WHERE id=%s", (tid,)
                ).scalar_one()
            result.update(
                task_id=str(tid),
                state=state,
                safe_error_code=error,
                model_calls_added=len(executions),
                executions=[
                    {k: str(v) if isinstance(v, UUID) else v for k, v in e.items()}
                    for e in executions
                ],
            )
            marker.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    finally:
        try:
            if grant_id:
                with engine.begin() as c:
                    exists = c.exec_driver_sql(
                        "SELECT id FROM grants WHERE org_id=%s AND id=%s",
                        (p.org_id, grant_id),
                    ).scalar_one_or_none()
                    if exists:
                        revoke(
                            c,
                            p,
                            uuid5(p.org_id, "s071:revoke:" + str(entry_id)),
                            grant_id,
                        )
                    revoked = c.exec_driver_sql(
                        "SELECT revoked_at IS NOT NULL FROM grants WHERE id=%s",
                        (grant_id,),
                    ).scalar_one_or_none()
                result.update(
                    temporary_grant_id=str(grant_id),
                    temporary_grant_revoked=bool(revoked),
                )
                if marker:
                    marker.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
                    )
        finally:
            engine.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except FileExistsError:
        print(
            "S07.1 request intent exists; inspect without reissuing.", file=sys.stderr
        )
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 - never expose secrets/provider bodies
        print("S07.1 validation stopped: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
