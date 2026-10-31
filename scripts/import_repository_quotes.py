"""Explicit owner-only import of pinned, locally frozen public quote repositories."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from app.core.database import build_engine
from app.knowledge.legacy_import import import_rows, parse_repository
from app.security.sessions import MemberPrincipal

from scripts.database import local_url


def bundles(root):
    tree = json.loads((root / "silver-tree.json").read_text())
    commit = json.loads((root / "silver-commit.json").read_text())
    if commit["sha"] != tree["sha"]:
        raise ValueError("Silver commit proof mismatch")
    if json.loads((root / "golden-original.json").read_text()) != json.loads(
        (root / "golden.json").read_text()
    ):
        raise ValueError("Golden source mismatch")
    records = []
    for entry in tree["tree"]:
        if not (
            entry["path"].startswith("movies/") and entry["path"].endswith("/meta.json")
        ):
            continue
        raw = (root / "silver" / entry["path"]).read_bytes()
        if (
            hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            != entry["sha"]
        ):
            raise ValueError("Silver Git blob mismatch")
        record = json.loads(raw)
        if entry["path"] != f"movies/{record['id']}/meta.json":
            raise ValueError("Source ID mismatch")
        records.append(record)
    index = json.loads((root / "silver-all.json").read_text())
    actual = {
        (r["id"], i): l["text"] for r in records for i, l in enumerate(r["lines"])
    }
    if actual != {(r["id"], r["i"]): r["text"] for r in index}:
        raise ValueError("Silver index mismatch")
    for project, commit, data in [
        (
            "golden",
            "7808d6c5035be35a077abac72f6ad22f357cac17",
            json.loads((root / "golden.json").read_text()),
        ),
        ("silver", tree["sha"], records),
    ]:
        bundle = {"project": project, "commit": commit, "records": data}
        text = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        path = root / (project + "-bundle.json")
        if path.exists() and path.read_text() != text:
            raise ValueError("Frozen bundle changed")
        if not path.exists():
            path.write_text(text)
        rows = parse_repository(bundle)
        yield bundle, text, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = ROOT / "data/knowledge-import/github"
    batches = list(bundles(root))
    report = {
        "date": "2026-10-23",
        "release_mode": "legacy_import",
        "model_calls": 0,
        "batches": [],
    }
    for b, text, rows in batches:
        report["batches"].append(
            {
                "project": b["project"],
                "commit": b["commit"],
                "total": len(rows),
                "lines": dict(Counter(r["line"] for r in rows)),
                "with_notes": sum(bool(r["note"]) for r in rows),
                "max_evidence_chars": max(
                    len(r["locations"][0]["original"]) for r in rows
                ),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    if args.execute:
        engine = build_engine(local_url())
        try:
            for (bundle, text, rows), summary in zip(batches, report["batches"]):
                with engine.begin() as c:
                    m = c.exec_driver_sql(
                        "SELECT m.org_id,m.id FROM members m JOIN organizations o ON o.id=m.org_id WHERE o.name='本地单人工作区' AND m.login_name='__local_owner__' AND m.disabled_at IS NULL"
                    ).one()
                    repo = (
                        "XFJ-YYQF/Golden-Sentence-Collection"
                        if bundle["project"] == "golden"
                        else "shenlq1017/silver-lines"
                    )
                    result = import_rows(
                        c,
                        MemberPrincipal(m.org_id, m.id),
                        rows,
                        source_text=text,
                        source_name=f"https://github.com/{repo}/tree/{bundle['commit']}",
                        category="quote",
                        reason="2026-10-23 用户明确要求直接导入两个金句项目；中文A线、英文B线；保留来源、说话人与标签，不执行AI审核。",
                        source_kind="repository",
                    )
                    summary.update(result)
                    if result["created"]:
                        # This connection can see the new rows; other sessions cannot
                        # produce useful statistics until this transaction commits.
                        for table in (
                            "knowledge_items",
                            "knowledge_revisions",
                            "knowledge_businesses",
                            "knowledge_evidence",
                            "knowledge_publications",
                            "search_documents",
                            "review_requests",
                            "evidence_refs",
                            "raw_assets",
                        ):
                            c.exec_driver_sql("ANALYZE " + table)
                        print(
                            json.dumps(
                                {
                                    "project": bundle["project"],
                                    "prepared": result["created"],
                                    "phase": "commit_with_fresh_statistics",
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                print(
                    json.dumps(
                        {k: v for k, v in summary.items() if k != "ids"},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            (
                root
                / ("receipt-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + ".json")
            ).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        finally:
            engine.dispose()
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
