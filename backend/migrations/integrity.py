"""Load a released migration only if its frozen checksum still matches."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent


def read_snapshot(filename):
    path = ROOT / "sql" / filename
    manifest = json.loads((ROOT / "manifest.json").read_text())
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["sql_sha256"].get(filename):
        raise RuntimeError("Released migration checksum changed; write a new revision instead.")
    return data.decode("utf-8")
