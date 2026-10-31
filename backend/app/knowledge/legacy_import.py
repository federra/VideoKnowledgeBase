"""Owner-only, explicit legacy import. Never manufactures review decisions or AI calls."""

import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5

from app.collection.service import insert
from app.core.repository import compare_and_swap
from app.knowledge.contracts import KnowledgeWrite, ManualSource
from app.knowledge.search import INDEX_VERSION, document, normalize
from app.knowledge.service import create
from app.security.errors import Denied
from app.security.storage import lock_org


def section_lines(text, start, end):
    active = False
    found_end = False
    result = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith(start):
            active = True
        elif active and line.startswith(end):
            found_end = True
            break
        elif active:
            result.append((n, line))
    if not active or not found_end:
        raise ValueError("Required source section is missing or incomplete")
    return result


def parse_quotes(text):
    rows = {}
    seen = set()
    group = ""
    for n, line in section_lines(text, "## 二、共鸣金句库", "## 三、18爽点内核库"):
        if line.startswith("#### "):
            group = line[5:]
        match = re.fullmatch(r'(\d+)\. "(.*)"(.*)', line)
        if not match:
            continue
        number, quote, note = match.groups()
        if number in seen or not quote.strip() or not group:
            raise ValueError("Invalid quote numbering or group")
        seen.add(number)
        row = rows.setdefault(
            quote, {"text": quote, "code": "Q" + number, "note": note.strip(), "locations": []}
        )
        row["locations"].append({"number": number, "line": n, "group": group, "original": line})
    if not rows:
        raise ValueError("No quotes found")
    return list(rows.values())


def parse_genres(text):
    rows = []
    seen = set()
    group = ""
    for n, line in section_lines(
        text, "# 模块16 · 海外本土化 + 140+题材库", "## 四、A↔B对应速查表"
    ):
        if line.startswith(("### ", "#### ")):
            group = line.lstrip("# ")
        match = re.fullmatch(r"((?:BF|BM|M|F|S)\d{2}) · (.+)", line)
        if not match:
            continue
        code, name = match.groups()
        if code in seen:
            raise ValueError("Duplicate genre code")
        seen.add(code)
        rows.append(
            {
                "text": name,
                "code": code,
                "note": "",
                "locations": [{"number": code, "line": n, "group": group, "original": line}],
            }
        )
    if not rows:
        raise ValueError("No genres found")
    return rows


def parse_failures(text):
    lines = section_lines(text, "## 二、41翻车点完整清单", "## 三、`/anti_pattern` 命令规范")
    rows = []
    group = ""
    current = None

    def finish():
        if current is None:
            return
        body = "\n".join(current.pop("lines")).strip()
        if any(
            not re.search(r"^\*\*" + field + r"\*\*：\S.+$", body, re.MULTILINE)
            for field in ("描述", "后果", "修复")
        ):
            raise ValueError("Incomplete failure entry")
        current["body"] = body
        current["locations"][0]["original"] = body
        rows.append(current)

    for n, line in lines:
        if line.startswith("### "):
            finish()
            current = None
            group = line[4:]
        elif line.startswith("#### "):
            finish()
            match = re.fullmatch(r"#### (TP\d{2}) · (.+)", line)
            if not match or not group:
                raise ValueError("Invalid failure heading or group")
            code, title = match.groups()
            if code != f"TP{len(rows) + 1:02}":
                raise ValueError("Missing or duplicate failure code")
            current = {
                "text": title,
                "code": code,
                "note": "",
                "lines": [line],
                "locations": [{"number": code, "line": n, "group": group}],
            }
        elif current is not None:
            current["lines"].append(line)
    finish()
    if not rows:
        raise ValueError("No failures found")
    return rows


def parse_payoffs(text):
    rows = []
    for n, line in section_lines(text, "### 3.1 18爽点完整清单", "### 3.2 "):
        if not re.match(r"^\d+\.", line):
            continue
        match = re.fullmatch(r"(\d+)\. ([^：]+)：(\S.*)", line)
        if not match or int(match[1]) != len(rows) + 1:
            raise ValueError("Invalid payoff numbering or description")
        number, title, description = match.groups()
        rows.append(
            {
                "text": title,
                "code": f"P{int(number):02}",
                "note": "",
                "body": title + "：" + description,
                "locations": [
                    {"number": number, "line": n, "group": "18爽点内核库", "original": line}
                ],
            }
        )
    if not rows:
        raise ValueError("No payoffs found")
    return rows


def parse_repository(bundle):
    """Read pinned repository records, preserving source-specific attribution."""
    project, commit = bundle["project"], bundle["commit"]
    if project not in ("golden", "silver") or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Unsupported repository or commit")
    rows, seen = [], set()
    for record in bundle["records"]:
        identity = str(record["id"])
        if identity in seen:
            raise ValueError("Duplicate source identity")
        seen.add(identity)
        lines = [record] if project == "golden" else record["lines"]
        source = None if project == "golden" else record["film"]["title"]
        tags = [record["tag"]] if project == "golden" else record.get("tags", [])
        for index, entry in enumerate(lines):
            for field in ("text", "en"):
                text = entry.get(field)
                if text is None or text == "":
                    if field == "text":
                        raise ValueError("Missing quote text")
                    continue
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Invalid quote text")
                text = text.strip()
                # Only assign the explicitly requested Chinese/English branches.
                if re.search(r"[\u3400-\u9fff]", text):
                    line = "A"
                elif re.search(r"[A-Za-z]", text):
                    line = "B"
                else:
                    raise ValueError("Unrecognized quote language")
                code = f"{project}:{identity}:{index}:{field}"
                path = "seed-data.json" if project == "golden" else f"movies/{identity}/meta.json"
                rows.append(
                    {
                        "text": text,
                        "body": text,
                        "code": code,
                        "note": entry.get("note") or "",
                        "source_text": source,
                        "explanation": (
                            entry.get("author") if project == "golden" else entry.get("character")
                        )
                        or None,
                        "tags": list(
                            dict.fromkeys(t for t in tags if isinstance(t, str) and t.strip())
                        ),
                        "line": line,
                        "locations": [
                            {
                                "number": code,
                                "line": index + 1,
                                "group": path,
                                "original": json.dumps(
                                    {
                                        "commit": commit,
                                        "record": record,
                                        "line_index": index,
                                        "field": field,
                                    },
                                    ensure_ascii=False,
                                    sort_keys=True,
                                ),
                            }
                        ],
                    }
                )
    if not rows:
        raise ValueError("Empty repository bundle")
    return rows


def import_rows(c, p, rows, *, source_text, source_name, category, reason, source_kind="legacy"):
    """Caller owns transaction; privileged CLI only, no HTTP route or general bypass."""
    owner = c.exec_driver_sql(
        "SELECT current_user=tableowner FROM pg_tables WHERE schemaname='public' AND tablename='knowledge_publications'"
    ).scalar_one()
    if not owner:
        raise Denied("ACCESS_DENIED")
    if not reason.strip() or category not in ("quote", "genre", "failure", "payoff"):
        raise ValueError("Explicit reason and supported category required")
    # Reject caller-supplied rows differing from the frozen source.
    if (
        source_kind not in ("legacy", "repository")
        or source_kind == "repository"
        and category != "quote"
    ):
        raise ValueError("Unsupported import source")
    expected = (
        parse_repository(json.loads(source_text))
        if source_kind == "repository"
        else {
            "quote": parse_quotes,
            "genre": parse_genres,
            "failure": parse_failures,
            "payoff": parse_payoffs,
        }[category](source_text)
    )
    if rows != expected:
        raise ValueError("Rows differ from source")
    lock_org(c, p.org_id)
    sha = hashlib.sha256(source_text.encode()).hexdigest()
    created = 0
    ids = []
    for row in rows:
        key = uuid5(NAMESPACE_URL, f"cip-legacy-v1:{p.org_id}:{sha}:{category}:{row['code']}")
        locations = row["locations"]
        groups = row.get("tags", list(dict.fromkeys(x["group"] for x in locations)))
        attribution = (
            source_name
            + "\nSHA256："
            + sha
            + "\n"
            + "\n".join(f"第{x['line']}行 · {x['group']} · 原编号{x['number']}" for x in locations)
        )
        body = row["text"] + ("\n原文表演备注：" + row["note"] if row["note"] else "")
        if category == "genre":
            body = f"{row['code']} · {body}\n来源分组：" + "；".join(groups)
        req = KnowledgeWrite(
            title=row["text"],
            body_text=row.get("body", body),
            source_text=row.get("source_text"),
            explanation=row.get("explanation"),
            knowledge_type="method_rule" if category == "failure" else "content_atom",
            browse_category=category,
            business_codes=["motion_comic", "story_short"],
            tags=[
                {
                    "kind": "stage",
                    "code": "script" if category in ("quote", "failure", "payoff") else "topic",
                },
                *[{"kind": "genre", "code": g} for g in groups],
                *([{"kind": "task", "code": "quote_line_" + row["line"]}] if "line" in row else []),
            ],
            limitations="用户确认的存量导入；未执行AI审核，不代表效果已验证。保留原文，不将来源中的热门判断作为实测结论。"
            + (
                ("\n原仓库说明：" + row["note"])
                if source_kind == "repository" and row["note"]
                else ""
            ),
            manual_source=ManualSource(
                body_text="\n".join(x["original"] for x in locations), attribution=attribution
            ),
        )
        item = create(c, p, key, req)
        rid, kid = item["revision_id"], item["id"]
        # Receipt replays the identity. Never import a later edited revision.
        rev = (
            c.exec_driver_sql(
                "SELECT * FROM knowledge_revisions WHERE org_id=%s AND knowledge_id=%s AND version_no=1",
                (p.org_id, kid),
            )
            .mappings()
            .one()
        )
        rid = rev["id"]
        old = c.exec_driver_sql(
            "SELECT id FROM knowledge_publications WHERE org_id=%s AND revision_id=%s",
            (p.org_id, rid),
        ).scalar_one_or_none()
        if not old:
            if item["revision_id"] != rid:
                raise ValueError("Candidate changed before import publication")
            pub = insert(
                c,
                "knowledge_publications",
                p.org_id,
                knowledge_id=kid,
                revision_id=rid,
                published_by=p.member_id,
                release_mode="legacy_import",
                import_metadata={
                    "source_sha256": sha,
                    "source_name": source_name,
                    "source_code": row["code"],
                    "reason": reason,
                    "locations": locations,
                },
            )
            compare_and_swap(
                c,
                "knowledge_items",
                p.org_id,
                kid,
                int(item["lock_version"]),
                {"published_publication_id": pub},
            )
            text = document(rev)
            folded = normalize(text)
            vector = c.exec_driver_sql(
                "SELECT to_tsvector('simple',%s)",
                (" ".join(folded[i : i + 2] for i in range(max(1, len(folded) - 1))),),
            ).scalar_one()
            insert(
                c,
                "search_documents",
                p.org_id,
                publication_id=pub,
                revision_id=rid,
                document_text=text,
                search_vector=vector,
                index_config_version=INDEX_VERSION,
            )
            insert(
                c,
                "audit_events",
                p.org_id,
                actor_member_id=p.member_id,
                action_code="knowledge.legacy_imported",
                request_id=str(key),
                target_kind="knowledge",
                target_id=kid,
                safe_details={
                    "source_sha256": sha,
                    "source_code": row["code"],
                    "reason": reason,
                    "revision_id": str(rid),
                },
            )
            created += 1
        ids.append(str(kid))
    return {"created": created, "total": len(ids), "ids": ids, "source_sha256": sha}
