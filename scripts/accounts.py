"""Controlled local onboarding and session-authorized governance. Passwords use getpass only."""

import argparse
import getpass
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts.database import local_url

from app.core.database import application_engine
from app.security import governance as g
from app.security.errors import Denied
from app.security.sessions import authenticate, csrf_for, login, logout


def password(label):
    value = getpass.getpass(label)
    if value != getpass.getpass("Repeat password: "):
        raise ValueError("Password confirmation differs.")
    return value


def recovery_key(supplied):
    key = supplied or uuid4()
    print("Recovery Idempotency-Key: " + str(key), file=sys.stderr, flush=True)
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "bootstrap",
            "member-add",
            "member-disable",
            "grant",
            "revoke",
            "role-set",
            "audit",
            "roles",
            "members",
        ],
    )
    parser.add_argument("--org", type=UUID)
    parser.add_argument("--org-name")
    parser.add_argument("--login", required=True)
    parser.add_argument("--name")
    parser.add_argument("--target", type=UUID)
    parser.add_argument("--role", type=UUID)
    parser.add_argument(
        "--scope",
        choices=[
            "org",
            "business",
            "source",
            "raw_asset",
            "work",
            "knowledge",
            "standard",
            "file",
            "task",
        ],
    )
    parser.add_argument("--scope-id")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--action", action="append")
    parser.add_argument("--new-login")
    parser.add_argument("--key", type=UUID, default=None)
    args = parser.parse_args()
    local_url()  # Dedicated local environment only; no accidental remote onboarding.
    engine = application_engine()
    try:
        if args.command == "bootstrap":
            if not args.org_name or args.org:
                parser.error("bootstrap requires --org-name, no existing --org")
            secret = password("Initial administrator password (15+ characters): ")
            with engine.begin() as c:
                org, member = g.bootstrap(c, args.org_name, args.login, secret)
            print(
                json.dumps(
                    {"org_id": str(org), "member_id": str(member)}, ensure_ascii=False
                )
            )
            return
        if not args.org:
            parser.error("--org is required")
        raw, _ = login(
            engine,
            args.org,
            args.login,
            getpass.getpass("Administrator password: "),
            "local-cli",
        )
        key = recovery_key(args.key)
        # Gather passwords before acquiring the tenant transaction lock.
        new_password = (
            password("New member password (15+ characters): ")
            if args.command == "member-add"
            else None
        )
        try:
            with engine.begin() as c:
                p = authenticate(c, raw)
                if args.command == "member-add":
                    if not args.new_login:
                        parser.error("--new-login is required")
                    result = g.create_member(
                        c,
                        p,
                        key,
                        args.new_login,
                        args.name or args.new_login,
                        new_password,
                    )
                elif args.command == "member-disable":
                    if (
                        not args.target
                        or not args.expected_version
                        or args.expected_version < 1
                    ):
                        parser.error(
                            "--target and positive --expected-version required"
                        )
                    result = g.disable_member(
                        c, p, key, args.target, args.expected_version
                    )
                elif args.command == "grant":
                    if not args.target or not args.role or not args.scope:
                        parser.error("--target member, --role and --scope required")
                    target = (
                        args.scope_id
                        if args.scope == "business"
                        else UUID(args.scope_id)
                        if args.scope_id
                        else None
                    )
                    result = g.delegate(
                        c, p, key, args.target, args.role, args.scope, target
                    )
                elif args.command == "revoke":
                    if not args.target:
                        parser.error("--target grant required")
                    result = g.revoke(c, p, key, args.target)
                elif args.command == "role-set":
                    if not args.target or not args.action:
                        parser.error("--target role and repeated --action required")
                    result = g.set_role_actions(c, p, key, args.target, args.action)
                elif args.command in ("roles", "members"):
                    result = g.catalog(c, p, args.command)
                else:
                    result = g.read_audit(c, p)
            print(
                json.dumps(
                    {"idempotency_key": str(key), "result": result},
                    default=str,
                    ensure_ascii=False,
                )
            )
        finally:
            # Disabling oneself can already invalidate the session. Revoke its row under
            # the same tenant lock even if ordinary authenticate now rejects it.
            try:
                with engine.begin() as c:
                    logout(c, raw, csrf_for(raw))
            except Denied:
                pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Denied as exc:
        print("Account command denied: " + exc.code, file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - no driver values or credentials in CLI output
        print("Account command failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
