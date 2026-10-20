"""Controlled local collection configuration; submitting a job permits one paid request."""

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

from app.collection.service import configure_connection, configure_source, submit
from app.connectors.redfox import VERSION
from app.contracts.models import CollectionCreate
from app.core.database import application_engine
from app.security.sessions import authenticate, csrf_for, login, logout
from app.tasks.handlers import registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["connection-add", "source-add", "start"])
    parser.add_argument("--org", required=True, type=UUID)
    parser.add_argument("--login", required=True)
    parser.add_argument("--name")
    parser.add_argument("--kind", choices=["keyword", "account"])
    parser.add_argument("--value")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--source", type=UUID)
    parser.add_argument("--connection", type=UUID)
    parser.add_argument("--capability", choices=["douyin.account.search", "douyin.creator.works"])
    parser.add_argument("--max-items", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--key", type=UUID)
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if args.action == "start" and not all(
        (args.source, args.connection, args.capability, args.key, args.allow_paid)
    ):
        parser.error(
            "start requires --source --connection --capability --key --allow-paid (one request)"
        )
    if args.action == "connection-add" and not args.name:
        parser.error("--name required")
    if args.action == "source-add" and not all((args.name, args.kind, args.value)):
        parser.error("--name --kind --value required")
    local_url()
    engine = application_engine()
    raw = None
    try:
        raw, _ = login(
            engine, args.org, args.login, getpass.getpass("Password: "), "local-collection-cli"
        )
        with engine.begin() as c:
            p = authenticate(c, raw)
            if args.action == "connection-add":
                result = {"connection_id": str(configure_connection(c, p, args.name))}
            elif args.action == "source-add":
                result = {
                    "source_id": str(
                        configure_source(
                            c, p, args.name, args.kind, args.value, enabled=args.enabled
                        )
                    )
                }
            else:
                request = CollectionCreate(
                    source_id=args.source,
                    provider_connection_id=args.connection,
                    capability_code=args.capability,
                    max_items=args.max_items,
                )
                result = submit(
                    c, p, request, str(args.key), registry()[("collect.redfox", VERSION)]
                )
        print(json.dumps(result))
    finally:
        if raw:
            with engine.begin() as c:
                logout(c, raw, csrf_for(raw))
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - never print provider/driver secrets
        print("Collection command failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
