"""Export/check the S07.1 task definition snapshot; no model or database I/O."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.deepseek import MODEL
from app.ai.research import DEFINITIONS, ResearchInput, system_prompt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = {
        "schema_version": 1,
        "status": "definition_baseline",
        "model": MODEL,
        "live_validation_target": "research.decompose.v1",
        "input_schema": ResearchInput.model_json_schema(),
        "tasks": {
            f"research.{kind}.v1": {
                "output_schema": schema.model_json_schema(),
                "system_prompt": system_prompt(kind),
                "system_sha256": hashlib.sha256(
                    system_prompt(kind).encode()
                ).hexdigest(),
            }
            for kind, schema in DEFINITIONS.items()
        },
    }
    body = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path = ROOT / "doc/technical/ai/research-task-definitions.json"
    if args.check:
        if not path.exists() or path.read_text() != body:
            raise SystemExit("S07.1 definition snapshot drift")
        print("S07.1 definition snapshot matches code.")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        print("S07.1 definition snapshot exported.")


if __name__ == "__main__":
    main()
