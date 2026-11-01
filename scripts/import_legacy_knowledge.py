"""Explicit local owner import of user-confirmed K09 quotes, K10 genres or K08 failures."""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from app.core.database import build_engine
from app.knowledge.legacy_import import (
    import_rows,
    parse_failures,
    parse_genres,
    parse_payoffs,
    parse_quotes,
)
from app.security.local import owner_identity
from app.security.sessions import MemberPrincipal

from scripts.database import local_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quotes", type=Path)
    parser.add_argument("--genres", type=Path)
    parser.add_argument("--failures", type=Path)
    parser.add_argument("--payoffs", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not any((args.quotes, args.genres, args.failures, args.payoffs)):
        parser.error("Supply at least one source file")
    batches = []
    for path, category, parse, expected in [
        (args.quotes, "quote", parse_quotes, 199),
        (args.genres, "genre", parse_genres, 140),
        (args.failures, "failure", parse_failures, 41),
        (args.payoffs, "payoff", parse_payoffs, 18),
    ]:
        if path is None:
            continue
        text = path.read_bytes().decode("utf-8")
        rows = parse(text)
        if len(rows) != expected:
            raise ValueError(
                f"{category}: expected {expected}, got {len(rows)}; inspect changed source"
            )
        batches.append((path, category, text, rows))
    if not args.execute:
        print(
            json.dumps(
                {category: len(rows) for _, category, _, rows in batches},
                ensure_ascii=False,
            )
        )
        return
    # Freeze source bytes before committing any business records.
    target = ROOT / "data/knowledge-import" / datetime.now().strftime("%Y-%m-%d")
    target.mkdir(parents=True, exist_ok=True)
    for path, _, text, _ in batches:
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        frozen = target / (sha + "-" + path.name)
        if frozen.exists() and frozen.read_bytes() != text.encode("utf-8"):
            raise ValueError("Frozen source conflict")
        if not frozen.exists():
            frozen.write_bytes(text.encode("utf-8"))
    # Credentials stay private; only the dedicated loopback database is permitted.
    engine = build_engine(local_url())
    report = {
        "external_calls": 0,
        "model_calls": 0,
        "release_mode": "legacy_import",
        "batches": [],
    }
    try:
        with engine.begin() as c:
            member = owner_identity(c)
            p = MemberPrincipal(member.org_id, member.id)
            for path, category, text, rows in batches:
                result = import_rows(
                    c,
                    p,
                    rows,
                    source_text=text,
                    source_name=str(path),
                    category=category,
                    reason=(
                        "2026-10-22 用户确认K09的18爽点直接导入，保留原文和来源，不执行AI审核。"
                        if category == "payoff"
                        else "2026-10-21 用户指定导入K08模块10已有41翻车点，沿用存量直接导入，不执行AI审核。"
                        if category == "failure"
                        else "2026-10-21 用户确认：直接导入即可；已有金句与模块16题材作为存量正式知识，不执行AI审核。"
                    ),
                )
                report["batches"].append({"category": category, **result})
        receipt_name = (
            "receipt-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
        )
        (target / receipt_name).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    **report,
                    "batches": [
                        {k: v for k, v in b.items() if k != "ids"}
                        for b in report["batches"]
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
