"""S05.4 controlled local task CLI; passwords prompted, never passed as arguments."""

import argparse
import getpass
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from scripts.database import local_url

from app.core.database import application_engine
from app.security.authorization import Authorizer
from app.security.sessions import authenticate, csrf_for, login, logout
from app.tasks.handlers import registry
from app.tasks.service import Runner, cancel, retry, submit_file, sweep
from app.tasks.worker import dispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["tick", "submit-file", "status", "cancel", "retry"]
    )
    parser.add_argument("--org", type=UUID)
    parser.add_argument("--login")
    parser.add_argument("--file", type=UUID)
    parser.add_argument("--task", type=UUID)
    parser.add_argument("--key")
    parser.add_argument("--expected", type=int)
    parser.add_argument("--max-attempts", type=int, default=1)
    args = parser.parse_args()
    local_url()
    engine = application_engine()
    runner = Runner(engine, registry())
    raw = None
    try:
        if args.action == "tick":
            from app.collection.schedule import schedule
            scheduled = schedule(runner)
            print(json.dumps({**sweep(runner, dispatch), "scheduled": scheduled}))
            return
        if not args.org or not args.login:
            parser.error("--org and --login required")
        raw, _ = login(
            engine,
            args.org,
            args.login,
            getpass.getpass("Password: "),
            "local-task-cli",
        )
        if args.action == "submit-file":
            if not args.file or not args.key:
                parser.error("--file and --key required")
            tid, created = submit_file(
                engine, raw, args.file, args.key, max_attempts=args.max_attempts
            )
            # Durable row survives Redis outage; next Beat tick dispatches it.
            print(
                json.dumps({"task_id": str(tid), "created": created, "state": "queued"})
            )
        else:
            if not args.task:
                parser.error("--task required")
            with engine.begin() as c:
                p = authenticate(c, raw)
                if args.action == "status":
                    value = Authorizer(c, p).read("tasks", args.task)
                    print(json.dumps(value, default=str))
                else:
                    if args.expected is None:
                        parser.error("--expected lock_version required")
                    value = (
                        cancel(c, p, args.task, args.expected)
                        if args.action == "cancel"
                        else retry(c, p, args.task, args.expected, runner)
                    )
                    print(json.dumps({"result": value}))
    finally:
        if raw:
            with engine.begin() as c:
                logout(c, raw, csrf_for(raw))
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - avoid secrets in driver exception strings
        print("Task command failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
