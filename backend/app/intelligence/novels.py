"""Same-day, authorized official novel snapshots; book memberships filter before dedup."""

from app.intelligence.service import novel_raw_ids, row, selected
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import refresh


def feed(
    c, p, business, day, *, platform="all", rank_type=None, gender=None, genre=None, page=1, q=None
):
    refresh(c, p)
    pairs = selected(c, p, business, day, platforms=("fanqie", "qidian"))
    statistics_note = None
    members = []
    boards = {}
    genre_by_platform = {"fanqie": set(), "qidian": set()}
    taxonomy_by_board = {}
    catalog_genders = {}
    statuses = []
    az = Authorizer(c, p)
    for snap, values in pairs:
        job = row(c, "collection_jobs", p.org_id, snap["job_id"])
        board = job["safe_request"]
        boards[board["code"]] = board
        if board["platform"] == "fanqie":
            genre_by_platform["fanqie"].add(board["category_name"])
        for value in values:
            meta = value.pop("_novel", None)
            if not meta:
                raise Denied("SOURCE_UNAVAILABLE")
            if board["platform"] == "qidian":
                genre_by_platform["qidian"].update(meta.get("taxonomy", []))
                taxonomy_by_board.setdefault(board["code"], set()).update(meta.get("taxonomy", []))
            members.append(
                {
                    "item": value,
                    "_work_fields": value.pop("_novel_work_fields", {"gender": None, "genres": []}),
                    "_taxonomy": meta.get("taxonomy", [])
                    if board["platform"] == "qidian"
                    else None,
                    "reader_count": str(meta["reader_count"])
                    if meta["reader_count"] is not None
                    else None,
                    "rank": meta["rank"],
                    "board": board,
                }
            )
    # Report actual task/HTTP outcomes. Paused sources remain readable; withdrawn evidence does not.
    jobs = c.exec_driver_sql(
        "SELECT j.*,t.state,cc.http_status FROM collection_jobs j JOIN sources s ON s.org_id=j.org_id AND s.id=j.source_id JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id LEFT JOIN collection_calls cc ON cc.org_id=j.org_id AND cc.job_id=j.id WHERE j.org_id=%s AND j.business_code=%s AND j.business_date=%s AND s.platform_code IN ('fanqie','qidian') ORDER BY j.created_at DESC",
        (p.org_id, business, day),
    ).mappings()
    seen = set()
    for job in jobs:
        source_id = job["source_id"]
        if source_id in seen:
            continue
        seen.add(source_id)
        try:
            source = az.require("sources", source_id, "content.read")
            raws = novel_raw_ids(c, p.org_id, job["id"])
            for raw in raws:
                az.read("raw_assets", raw)
        except Denied as exc:
            if exc.code in ("NOT_FOUND", "ACCESS_DENIED"):
                continue
            raise
        board = job["safe_request"]
        if board.get("rank_type") == "catalog" and board.get("gender") in ("male", "female"):
            catalog_genders.setdefault((board["platform"], board["gender"]), job["http_status"])
        if (
            board["platform"] == "fanqie"
            and board.get("rank_type") == "catalog"
            and job["state"] == "succeeded"
            and raws
        ):
            import re

            body = row(c, "raw_assets", p.org_id, raws[0])["body_text"]
            found = re.search(r"统计时间截止至(?:<!--.*?-->)*(\d{2}-\d{2} 24:00)", body)
            if found:
                statistics_note = "统计时间截止至" + found[1] + "（平台原文）"
        statuses.append(
            {
                "platform": source["platform_code"],
                "board": board["code"],
                "state": job["state"],
                "http_status": job["http_status"],
                "_method": board.get("method"),
            }
        )
        if job["state"] == "succeeded" and board.get("rank_type") != "catalog":
            boards[board["code"]] = board

    def identity(value):
        o = value["item"]["entry"]["observation"]
        return o["platform_code"], o["platform_id"]

    novel_count = str(len({identity(v) for v in members})) if pairs else None
    visible_boards = [b for b in boards.values() if platform == "all" or b["platform"] == platform]
    genre_names = set().union(
        *(
            names
            for code, names in genre_by_platform.items()
            if platform == "all" or code == platform
        )
    )
    for value in members:
        fields = value.pop("_work_fields")
        own_taxonomy = value.pop("_taxonomy")
        allowed_genres = (
            own_taxonomy
            if own_taxonomy is not None
            else genre_by_platform[value["board"]["platform"]]
        )
        value["work_gender"] = fields["gender"]
        value["work_genre"] = next(
            (g for g in fields["genres"] if g in allowed_genres),
            None,
        )

    rank_labels = {}
    rank_platforms = {}
    for b in visible_boards:
        rank_labels[b["rank_type"]] = b.get("rank_name") or {"read": "阅读榜", "new": "新书榜"}.get(
            b["rank_type"], b["rank_type"]
        )
        rank_platforms[b["rank_type"]] = b["platform"]
    rank_options = []
    for kind, label in sorted(rank_labels.items()):
        if list(rank_labels.values()).count(label) > 1:
            label += " · " + ("番茄" if rank_platforms[kind] == "fanqie" else "起点")
        rank_options.append({"value": kind, "label": label})

    available_genders = {b["gender"] for b in visible_boards}
    gender_values = available_genders | {
        value for (code, value) in catalog_genders if platform == "all" or code == platform
    }
    gender_options = []
    for value in sorted(gender_values):
        label = {"male": "男频", "female": "女频", "all": "全部"}.get(value, value)
        option = {"value": value, "label": label}
        if value not in available_genders:
            codes = [
                status
                for (code, g), status in catalog_genders.items()
                if g == value and (platform == "all" or code == platform) and status != 200
            ]
            option.update(
                disabled=True,
                reason=label
                + "目录尚无可访问榜单"
                + (f"（HTTP {codes[0]}）" if codes and codes[0] is not None else ""),
            )
        gender_options.append(option)

    genre_options = []
    for name in sorted(genre_names):
        usable = any(
            (not gender or b["gender"] == gender)
            and (not rank_type or b["rank_type"] == rank_type)
            and (
                b["category_name"] == name
                if b["platform"] == "fanqie"
                else name in taxonomy_by_board.get(b["code"], set())
            )
            for b in visible_boards
        )
        option = {"value": name, "label": name}
        if not usable:
            option.update(disabled=True, reason="当前男女频／榜型下无此题材分类")
        genre_options.append(option)

    matches = []
    seen_books = set()
    for value in sorted(members, key=lambda v: (v["board"]["code"], v["rank"])):
        b = value["board"]
        o = value["item"]["entry"]["observation"]
        if (
            platform != "all"
            and b["platform"] != platform
            or rank_type
            and b["rank_type"] != rank_type
            or gender
            and b["gender"] != gender
            or genre
            and (value["work_genre"] if b["platform"] == "qidian" else b["category_name"]) != genre
        ):
            continue
        if (
            q
            and q.casefold()
            not in " ".join(
                str(s or "")
                for s in (
                    o["display_name"],
                    o["description"],
                    value["item"]["author"],
                    b["category_name"],
                )
            ).casefold()
        ):
            continue
        key = identity(value)
        if key not in seen_books:
            matches.append(value)
            seen_books.add(key)
    # The frozen request includes private import lineage; expose only the stable board contract.
    from app.intelligence.novel_contracts import NovelBoard

    for value in matches:
        value["board"] = {k: v for k, v in value["board"].items() if k in NovelBoard.model_fields}
    return {
        "business_code": business,
        "business_date": day,
        "novel_count": novel_count,
        "statistics_note": statistics_note if platform != "qidian" else None,
        "page": page,
        "page_size": 10,
        "total": str(len(matches)),
        "items": matches[(page - 1) * 10 : page * 10],
        "rank_types": rank_options,
        "genders": gender_options,
        "genres": genre_options,
        "statuses": [
            {key: value for key, value in s.items() if key != "_method"}
            for s in statuses
            if (platform == "all" or s["platform"] == platform)
            and (
                s["platform"] != "qidian"
                or s["_method"] is not None
                or not any(x["platform"] == "qidian" and x["_method"] is not None for x in statuses)
            )
        ],
    }
