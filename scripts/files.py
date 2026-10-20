"""Deterministic local recovery of this service's durable file journals; no remote calls."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from scripts.database import local_url

from app.core.database import application_engine
from app.storage.http import get_store
from app.storage.service import recover


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["recover"])
    parser.parse_args()
    local_url()
    engine = application_engine()
    try:
        result = recover(engine, get_store())
        print(json.dumps(result))
        return 1 if result["unresolved"] else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - private configuration/driver errors are sanitized
        print("File recovery failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
