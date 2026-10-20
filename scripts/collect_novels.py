"""Explicit single local batch: discovered Fanqie boards <=30 each, Qidian catalog only if accessible."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.collection.novels import NovelCollect, submit
from app.connectors.fontcodec import spec
from app.connectors.novels import VERSION, PublicNovels, catalog
from app.core.config import settings
from app.core.database import application_engine
from app.core.repository import compare_and_swap
from app.intelligence.service import shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def font_urls(text):
    urls = []
    for block in re.findall(r"@font-face\s*\{[^}]+\}", text):
        if re.search(r"font-weight\s*:\s*400\b", block):
            urls += re.findall(
                r"https://lf6-awef\.bytetos\.com/obj/awesome-font/[^)\s\'\"]+\.otf",
                block,
            )
    return list(dict.fromkeys(urls))


def verify_font(html, directory):
    """Read styles referenced by the captured page; require the exact approved 400-weight font."""
    styles = re.findall(r"<link[^>]+href=[\'\"]([^\'\"]+\.css)[\'\"]", html)
    reads = []
    fonts = font_urls(html)
    with httpx.Client(timeout=25, follow_redirects=False) as client:

        def read(url, host):
            if urlsplit(url).scheme != "https" or urlsplit(url).hostname != host:
                raise RuntimeError("Untrusted metadata host")
            with client.stream("GET", url) as r:
                r.raise_for_status()
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > 3 * 1024 * 1024:
                        raise RuntimeError("Metadata too large")
            reads.append(
                {
                    "url": url,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            )
            return data

        if not fonts:
            for href in styles[:8]:
                url = "https:" + href if href.startswith("//") else href
                css = read(url, "lf-fe.fqnovelstatic.com").decode("utf-8")
                fonts += font_urls(css)
        fonts = list(dict.fromkeys(fonts))
        if not fonts:
            raise RuntimeError("Current font not discovered; no book calls")
        if len(fonts) != 1:
            raise RuntimeError("Ambiguous content fonts; no book calls")
        approved = spec()["font_sha256"]
        found = False
        for url in fonts:
            data = read(url, "lf6-awef.bytetos.com")
            sha = hashlib.sha256(data).hexdigest()
            if sha == approved:
                (directory / (sha + ".otf")).write_bytes(data)
                found = True
        if not found:
            raise RuntimeError(
                "Font changed; rebuild exact outline map before importing"
            )
    return reads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume local stopped batch; completed provider calls are never repeated",
    )
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "platforms": ["fanqie", "qidian"],
                    "max_boards": 74,
                    "per_board": 30,
                    "offset": 0,
                    "retries": 0,
                    "model_calls": 0,
                }
            )
        )
        return
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    directory = ROOT / "data/novels"
    directory.mkdir(parents=True, exist_ok=True)
    day = shanghai_date()
    marker = directory / f"batch-{day}.json"
    record = {"date": str(day), "status": "reserved", "jobs": [], "model_calls": 0}
    if args.resume:
        record = json.loads(marker.read_text())
        if record["date"] != str(day) or record["status"] != "stopped":
            raise RuntimeError("Only stopped current batch may resume")
    else:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)

    def save():
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

    engine = application_engine()
    handler = NovelCollect(PublicNovels())
    runner = Runner(engine, {("collect.novels", VERSION): handler})
    try:
        with engine.begin() as c:
            _, context = enter(c)
            p = MemberPrincipal(context["org_id"], context["member_id"])

        def run(board):
            saved = None
            try:
                with engine.begin() as c:
                    saved = submit(c, p, board, handler)
                with engine.begin() as c:
                    state = c.exec_driver_sql(
                        "SELECT state FROM tasks WHERE org_id=%s AND id=%s",
                        (p.org_id, UUID(saved["task_id"])),
                    ).scalar_one()
                if state == "queued":
                    runner.run(p.org_id, UUID(saved["task_id"]))
                with engine.begin() as c:
                    state = c.exec_driver_sql(
                        "SELECT state FROM tasks WHERE org_id=%s AND id=%s",
                        (p.org_id, UUID(saved["task_id"])),
                    ).scalar_one()
                    raw = c.exec_driver_sql(
                        "SELECT r.body_text FROM raw_assets r JOIN collection_jobs j ON j.org_id=r.org_id AND j.id=r.collection_job_id WHERE j.org_id=%s AND j.id=%s",
                        (p.org_id, UUID(saved["job_id"])),
                    ).scalar_one_or_none()
                    facts = (
                        c.exec_driver_sql(
                            "SELECT cc.http_status,cc.outcome,cc.returned_items FROM collection_calls cc WHERE cc.org_id=%s AND cc.job_id=%s",
                            (p.org_id, UUID(saved["job_id"])),
                        )
                        .mappings()
                        .all()
                    )
                    count = c.exec_driver_sql(
                        "SELECT coalesce(sum(entry_count),0) FROM intelligence_snapshots WHERE org_id=%s AND job_id=%s",
                        (p.org_id, UUID(saved["job_id"])),
                    ).scalar_one()
                record["jobs"] = [
                    j for j in record["jobs"] if j["board"] != board["code"]
                ]
                record["jobs"].append(
                    {
                        **saved,
                        "board": board["code"],
                        "state": state,
                        "saved": int(count),
                        "calls": [dict(x) for x in facts],
                    }
                )
                save()
                print(
                    json.dumps(
                        {"board": board["code"], "state": state, "saved": int(count)}
                    ),
                    flush=True,
                )
                return raw if state == "succeeded" else None
            finally:
                if saved:
                    with engine.begin() as c:
                        current = (
                            c.exec_driver_sql(
                                "SELECT lock_version,enabled FROM sources WHERE org_id=%s AND id=%s",
                                (p.org_id, UUID(saved["source_id"])),
                            )
                            .mappings()
                            .one()
                        )
                        if current["enabled"]:
                            compare_and_swap(
                                c,
                                "sources",
                                p.org_id,
                                UUID(saved["source_id"]),
                                current["lock_version"],
                                {"enabled": False},
                            )
                time.sleep(2.1)

        html = run(
            {
                "platform": "fanqie",
                "rank_type": "catalog",
                "code": "fanqie:catalog",
                "name": "官方目录",
            }
        )
        if html:
            boards = catalog(html)
            if len(boards) > 74:
                raise RuntimeError("Discovered more than approved 74 boards")
            record["font_metadata_reads"] = verify_font(html, directory)
            save()
            for board in boards:
                board.update(
                    font_sha256=spec()["font_sha256"],
                    name=("阅读榜" if board["rank_type"] == "read" else "新书榜")
                    + " · "
                    + ("男频" if board["gender"] == "male" else "女频")
                    + " · "
                    + board["category_name"],
                )
                run(board)
        run(
            {
                "platform": "qidian",
                "rank_type": "catalog",
                "code": "qidian:catalog",
                "name": "官方目录",
            }
        )
        record.pop("error_type", None)
        record["status"] = "finished"
        record["sources_paused"] = True
        save()
    except Exception as exc:
        record["status"] = "stopped"
        record["error_type"] = type(exc).__name__
        save()
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
