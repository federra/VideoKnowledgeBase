"""Sealed, same-date intelligence. Reads never submit collection or AI work."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.models import metadata
from app.security.errors import Denied
from app.security.sessions import refresh


def shanghai_date(moment=None):
    return (moment or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Shanghai")).date()


def row(c, name, org, ident, *, auth=None):
    if auth is not None:
        if auth.p.org_id != org:
            raise Denied("NOT_FOUND")
        return dict(auth.memo(("row",name,ident),lambda:row(c,name,org,ident)))
    t = metadata.tables[name]
    result = c.execute(select(t).where(t.c.org_id == org, t.c.id == ident)).mappings().one_or_none()
    if not result:
        raise Denied("NOT_FOUND")
    return dict(result)


def wire(value):
    return {
        k: value[k]
        for k in (
            "id",
            "created_at",
            "source_id",
            "job_id",
            "business_code",
            "business_date",
            "view_kind",
            "version_no",
            "entry_count",
            "sealed_at",
        )
    }


def novel_raw_map(c, org, job_ids):
    if not job_ids:
        return {}
    values = {ident:[] for ident in job_ids}
    rows = c.exec_driver_sql(
        "SELECT collection_job_id,id FROM raw_assets WHERE org_id=%s AND collection_job_id=ANY(%s) UNION "
        "SELECT j.id,r.id FROM collection_jobs j JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id "
        "JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id AND i.role IN ('novel_saved_html','novel_browser_ax') "
        "JOIN raw_assets r ON r.org_id=i.org_id AND r.id=i.raw_asset_id "
        "WHERE j.org_id=%s AND j.id=ANY(%s) AND ((j.safe_request->>'method'='qidian-desktop-html-v1' "
        "AND j.safe_request->>'capture_kind'='user_saved_html' AND i.role='novel_saved_html') OR "
        "(j.safe_request->>'method'='qidian-browser-ax-v1' AND j.safe_request->>'capture_kind'='browser_native_accessibility' AND i.role='novel_browser_ax')) "
        "AND j.capability_code='novel.qidian.board' "
        "AND t.max_external_calls=0 AND r.origin='manual' AND r.submitted_by=t.requested_by "
        "AND j.safe_request->>'raw_asset_id'=r.id::text AND j.safe_request->>'file_sha256'=r.sha256",
        (org,list(job_ids),org,list(job_ids)),
    )
    for job_id,raw_id in rows:
        values[job_id].append(raw_id)
    return values


def novel_raw_ids(c, org, job_id, *, auth=None):
    load=lambda:novel_raw_map(c,org,[job_id])[job_id]
    return auth.memo(("novel.raws",job_id),load) if auth else load()


def authorized(c, p, snap, auth=None):
    from app.security.read_authorizer import ReadAuthorizer

    auth = auth or ReadAuthorizer(c, p)
    source = auth.read("sources", snap["source_id"])
    scopes = {
        ("org", str(p.org_id)),
        ("source", str(source["id"])),
        ("business", snap["business_code"]),
    }
    if not auth.allowed("content.read", scopes):
        raise Denied("NOT_FOUND")
    work_fields = {}
    if source["platform_code"] in ("fanqie", "qidian", "qimao"):
        # Empty rankings still depend on a real response and its current authorization.
        raws = novel_raw_ids(c, p.org_id, snap["job_id"], auth=auth)
        if not raws:
            raise Denied("SOURCE_UNAVAILABLE")
        for raw_id in raws:
            captured = auth.read("raw_assets", raw_id)
            if source["platform_code"] == "fanqie":
                from app.connectors.novels import captured_book_fields
                from app.connectors.redfox import AdapterError

                try:
                    work_fields[raw_id] = captured_book_fields(captured["body_text"])
                except AdapterError:
                    raise Denied("SOURCE_UNAVAILABLE") from None
    def entry_rows():
        es=metadata.tables["snapshot_entries"]
        return [dict(r) for r in c.execute(select(es).where(
            es.c.org_id==p.org_id,es.c.snapshot_id==snap["id"]
        ).order_by(es.c.position)).mappings()]
    entry_rows = auth.memo(("snapshot.entries",snap["id"]),entry_rows)
    novel = source["platform_code"] in ("fanqie", "qidian", "qimao")
    result = []
    captured_batches = {}
    creator_dependencies = set()
    jobs = {}
    saved_hongguo_jobs = {}
    reused_page_jobs = {}
    for entry in entry_rows:
        kind = "account" if entry["account_observation_id"] else "content"
        if novel:
            obs = row(c,"content_observations",p.org_id,entry["content_observation_id"],auth=auth)
            if obs["raw_asset_id"] not in raws:
                raise Denied("SOURCE_UNAVAILABLE")
            identity = row(c,"external_contents",p.org_id,obs["content_id"],auth=auth)
        else:
            obs = row(c, kind + "_observations", p.org_id, entry[kind + "_observation_id"],auth=auth)
            auth.read("raw_assets", obs["raw_asset_id"])
            identity = row(
                c,
                "external_accounts" if kind == "account" else "external_contents",
                p.org_id,
                obs[kind + "_id"],
                auth=auth,
            )
        account = identity if kind == "account" else None
        captured_name = obs.get("nickname")
        captured_title = None
        if kind == "content":
            # Content.account_id is a mutable current identity association. Historical
            # author/filter membership comes from the sealed response instead.
            from app.connectors.redfox import AdapterError, normalize

            if novel:
                meta = next(
                    (
                        x
                        for x in (obs["source_tags"] or [])
                        if isinstance(x, dict) and x.get("kind") == "novel-v1"
                    ),
                    None,
                )
                if not meta:
                    raise Denied("SOURCE_UNAVAILABLE")
                captured = {
                    "account_display_name": meta.get("author"),
                    "display_name": meta["title"],
                }
            else:
                raw = auth.row("raw_assets", obs["raw_asset_id"])
                job_id = raw["collection_job_id"]
                if raw["origin"] == "api" and job_id != snap["job_id"]:
                    if raw["id"] not in reused_page_jobs:
                        if not c.exec_driver_sql(
                            "SELECT cip_page_reuse_allowed(%s,%s,%s)",
                            (p.org_id, snap["job_id"], raw["id"]),
                        ).scalar_one():
                            raise Denied("SOURCE_UNAVAILABLE")
                        reused_page_jobs[raw["id"]] = snap["job_id"]
                    # Validate the resumed complete chain, while the raw itself
                    # still supplies its original captured title and identity.
                    job_id = reused_page_jobs[raw["id"]]
                if job_id is None and raw["origin"] == "manual" and source["platform_code"] == "hongguo":
                    if raw["id"] not in saved_hongguo_jobs:
                        bound = c.exec_driver_sql(
                            "SELECT EXISTS(SELECT 1 FROM collection_jobs j "
                            "JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id "
                            "WHERE j.org_id=%s AND j.id=%s AND j.capability_code='hongguo.board' "
                            "AND t.kind='collect.hongguo.saved' AND t.state='succeeded' "
                            "AND cip_hongguo_saved_allowed(j.org_id,j.id,%s))",
                            (p.org_id, snap["job_id"], raw["id"]),
                        ).scalar_one()
                        if not bound:
                            raise Denied("SOURCE_UNAVAILABLE")
                        saved_hongguo_jobs[raw["id"]] = snap["job_id"]
                    job_id = saved_hongguo_jobs[raw["id"]]
                if job_id not in jobs:
                    jobs[job_id] = row(c, "collection_jobs", p.org_id, job_id)
                job = jobs[job_id]
                try:
                    from app.connectors import douyin_posts as posts
                    from app.connectors import douyin_search as microfilm
                    from app.connectors.douyin_series import CAPABILITY as CREATOR_CAP
                    from app.connectors.douyin_series import normalize_page
                    from app.connectors.hongguo import normalize_board
                    from app.connectors.tikhub_series import CAPABILITY as SERIES_CAP
                    from app.connectors.tikhub_series import normalize_series
                    if job['capability_code'] == posts.CAPABILITY and job['id'] not in creator_dependencies:
                        from app.collection.creator_posts import saved_pages
                        _, saved, _ = saved_pages(c, p.org_id, job, auth)
                        posts.combine(saved, job['safe_request']['sec_user_id'], job['safe_request']['uid'], job['safe_request']['window'])
                        creator_dependencies.add(job['id'])
                    if (
                        job["capability_code"] == microfilm.CAPABILITY
                        and raw["id"] in reused_page_jobs
                        and job["id"] not in creator_dependencies
                    ):
                        from app.intelligence.microfilm import saved_for_read

                        pages, _, _, _ = saved_for_read(c, p, job, auth)
                        microfilm.combine(pages)
                        creator_dependencies.add(job["id"])
                    if job['capability_code'] == CREATOR_CAP and job['id'] not in creator_dependencies:
                        from app.intelligence.creator_directory import require_directory
                        require_directory(c, p, job, auth)
                        creator_dependencies.add(job['id'])
                    if raw["id"] not in captured_batches:
                        batch = (
                            normalize_board(raw["body_text"], job["safe_request"]["board"])
                            if job["capability_code"] == "hongguo.board"
                            else normalize_series(json.loads(raw["body_text"]))
                            if job["capability_code"] == SERIES_CAP
                            else normalize_page(json.loads(raw["body_text"]), job["safe_request"]["sec_user_id"], job["safe_request"]["uid"])
                            if job["capability_code"] == CREATOR_CAP
                            else microfilm.search_page(json.loads(raw["body_text"]))
                            if job["capability_code"] == microfilm.CAPABILITY
                            else posts.normalize_page(json.loads(raw["body_text"]), job["safe_request"]["sec_user_id"], job["safe_request"]["uid"])
                            if job["capability_code"] == posts.CAPABILITY
                            else normalize(
                                job["capability_code"],
                                json.loads(raw["body_text"]),
                                maximum=job["max_items"],
                                target=job["safe_request"].get("userId"),
                            )
                        )
                        captured_batches[raw["id"]] = {
                            x["platform_content_id"]: x for x in batch.records
                        }
                    captured = captured_batches[raw["id"]][identity["platform_content_id"]]
                except (AdapterError, ValueError, StopIteration, KeyError):
                    raise Denied("SOURCE_UNAVAILABLE") from None
            captured_name = captured.get("account_display_name")
            captured_title = captured.get("display_name")
            if captured.get("platform_uid"):
                t = metadata.tables["external_accounts"]
                account = (
                    c.execute(
                        select(t).where(
                            t.c.org_id == p.org_id,
                            t.c.platform_code == identity["platform_code"],
                            t.c.platform_uid == captured["platform_uid"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        observation = {
            "id": obs["id"],
            "kind": kind,
            "platform_code": identity["platform_code"],
            "platform_id": identity["platform_uid" if kind == "account" else "platform_content_id"],
            "display_name": captured_title if kind == "content" else obs.get("nickname"),
            "description": obs.get("description"),
            "original_url": obs.get("original_url"),
            "observed_at": obs["observed_at"],
            "published_at_raw": obs.get("published_at_raw"),
            "published_at": obs.get("published_at"),
        }
        if identity["platform_code"] in ("fanqie", "qidian", "qimao"):
            from app.connectors.novel_metrics import reader_number

            observation["reader_count"] = (
                str(reader_number(meta["reader_count"]))
                if meta["reader_count"] is not None
                else None
            )
        if identity["platform_code"] == "qimao":
            observation["heat_value"] = str(meta["heat_value"]) if meta.get("heat_value") is not None else None
            observation["heat_display"] = meta.get("heat_display")
        for field in (
            "follower_count",
            "work_count",
            "like_count",
            "comment_count",
            "share_count",
            "collect_count",
            "repost_count",
            "view_count",
        ):
            number = obs.get(field)
            observation[field] = str(number) if number is not None else None
        result.append(
            {
                "entry": {
                    **{
                        k: entry[k]
                        for k in ("id", "created_at", "snapshot_id", "position", "provider_rank")
                    },
                    "observation": observation,
                    "feedback_id": None,
                },
                **(
                    {
                        "_novel": meta,
                        "_novel_work_fields": (
                            meta.get("work_fields", {"gender": None, "genres": []})
                            if source["platform_code"] in ("qidian", "qimao")
                            else work_fields.get(obs["raw_asset_id"], {}).get(
                                identity["platform_content_id"], {"gender": None, "genres": []}
                            )
                        ),
                    }
                    if novel
                    else {}
                ),
                "genre_tags": captured.get("genre_tags", []) if kind == "content" else [],
                "genre_hierarchy": captured.get("genre_hierarchy", []) if kind == "content" else [],
                "heat_display": captured.get("heat_display") if kind == "content" else None,
                "heat_value": str(captured["heat_value"])
                if kind == "content" and captured.get("heat_value") is not None
                else None,
                "score_display": captured.get("score_display") if kind == "content" else None,
                "source_id": snap["source_id"],
                "source_name": source["name"],
                "snapshot_version": snap["version_no"],
                "account_id": account["id"] if account else None,
                # Never use a mutable account nickname as the old snapshot's author name.
                "author": captured_name or ("UID:" + account["platform_uid"] if account else None),
            }
        )
    return result


def selected(c, p, business, day, source_id=None, view_kind=None, *, platforms=None, auth=None, board_capabilities=None):
    refresh(c, p)
    t = metadata.tables["intelligence_snapshots"]
    query = select(t).where(
        t.c.org_id == p.org_id,
        t.c.business_code == business,
        t.c.business_date == day,
        t.c.sealed_at.is_not(None),
    )
    from app.intelligence.refresh_visibility import visible_snapshots

    query = query.where(visible_snapshots())
    if platforms:
        sources = metadata.tables["sources"]
        query = query.join(
            sources, (sources.c.org_id == t.c.org_id) & (sources.c.id == t.c.source_id)
        ).where(sources.c.platform_code.in_(platforms))
    if board_capabilities is not None:
        from sqlalchemy import or_
        jobs = metadata.tables["collection_jobs"]
        query = query.join(jobs, (jobs.c.org_id == t.c.org_id) & (jobs.c.id == t.c.job_id)).where(or_(t.c.view_kind != "board", jobs.c.capability_code.in_(board_capabilities)))
    if source_id:
        query = query.where(t.c.source_id == source_id)
    if view_kind:
        query = query.where(t.c.view_kind == view_kind)
    from app.security.read_authorizer import ReadAuthorizer

    auth = auth or ReadAuthorizer(c, p)
    seen, result, latest = set(), [], []
    for value in c.execute(
        query.order_by(t.c.version_no.desc(), t.c.created_at.desc(), t.c.id.desc())
    ).mappings():
        key = (value["source_id"], value["view_kind"])
        if key in seen:
            continue
        seen.add(key)  # Latest withdrawn/denied evidence never falls back to old data.
        latest.append(dict(value))
    from app.intelligence.read_batch import prepare

    prepare(c,p,latest,auth)
    for value in latest:
        try:
            result.append((dict(value), authorized(c, p, value, auth)))
        except Denied as exc:
            if exc.code != "NOT_FOUND":
                raise
    return result


def snapshots(c, p, business, day, source_id=None, view_kind=None):
    return [wire(s) for s, _ in selected(c, p, business, day, source_id, view_kind)]


def entries(c, p, snapshot_id, page, page_size, q=None, account_id=None):
    refresh(c, p)
    snap = row(c, "intelligence_snapshots", p.org_id, snapshot_id)
    if not snap["sealed_at"]:
        raise Denied("NOT_FOUND")
    values = [
        x["entry"]
        for x in authorized(c, p, snap)
        if (not account_id or x["account_id"] == account_id)
        and (not q or q.casefold() in str(x["entry"]["observation"]).casefold())
    ]
    return {
        "snapshot_id": snapshot_id,
        "page": page,
        "page_size": page_size,
        "total": str(len(values)),
        "items": values[(page - 1) * page_size : page * page_size],
    }


def latest_video_dates(c, p, business, *, auth=None):
    latest_dates = {}
    # Stable dropdown history metadata; current-day absence never relabels historical rows.
    history = (
        c.exec_driver_sql(
            "SELECT DISTINCT s.source_id,s.business_date,j.capability_code FROM intelligence_snapshots s JOIN collection_jobs j ON j.org_id=s.org_id AND j.id=s.job_id WHERE s.org_id=%s AND s.business_code=%s AND s.sealed_at IS NOT NULL AND j.capability_code IN ('douyin.series.hot','hongguo.board') ORDER BY s.business_date DESC",
            (p.org_id, business),
        )
        .mappings()
        .all()
    )
    for value in history:
        catalog = "tikhub" if value["capability_code"] == "douyin.series.hot" else "hongguo"
        if catalog in latest_dates:
            continue
        if selected(c, p, business, value["business_date"], value["source_id"], "board", auth=auth):
            latest_dates[catalog] = value["business_date"]
    return latest_dates


def feed(
    c,
    p,
    business,
    day,
    lane="board",
    page=1,
    q=None,
    source_id=None,
    accounts=None,
    *,
    video_catalog=None,
    video_board=None,
    video_genre=None,
    video_subgenre=None,
):
    from app.security.read_authorizer import ReadAuthorizer

    auth = ReadAuthorizer(c, p)
    all_pairs = selected(c, p, business, day, auth=auth, platforms=("douyin", "hongguo"), board_capabilities=("douyin.search.microfilm",) if business == "story_short" else None)
    hongguo_pairs = [
        (s, rows)
        for s, rows in all_pairs
        if row(c, "sources", p.org_id, s["source_id"])["platform_code"] == "hongguo"
    ]
    pairs = [
        (s, rows)
        for s, rows in all_pairs
        if row(c, "sources", p.org_id, s["source_id"])["platform_code"] == "douyin"
    ]
    from app.intelligence.feedback import attach_previews
    from app.intelligence.insight import latest_insight

    for snap, values in pairs + hongguo_pairs:
        attach_previews(c, p, snap, values, auth=auth)
    from app.intelligence.ranking import keyword_board

    ranking_kinds = ("keyword_works", "board") if business == "motion_comic" else ("keyword_works",)
    keyword_rows = [v for snap, rows in pairs if snap["view_kind"] in ranking_kinds for v in rows]
    from app.connectors.redfox import KEYWORD_DEFAULT

    default_batch = None
    for snap, rows in pairs:
        if snap["view_kind"] != "keyword_works":
            continue
        job = row(c, "collection_jobs", p.org_id, snap["job_id"])
        eligible = job["capability_code"] == KEYWORD_DEFAULT and job["safe_request"] == {
            "keyword": "漫剧",
            "offset": 0,
            "sortType": "_0",
        }
        newest = default_batch is None or (snap["created_at"], str(snap["id"])) > (
            default_batch[0]["created_at"],
            str(default_batch[0]["id"]),
        )
        if eligible and newest:
            default_batch = (snap, rows)
    ranking = keyword_board(keyword_rows, default_rows=default_batch[1] if default_batch else None)
    # A verified daily-category batch supersedes keyword candidates without relabeling them.
    from app.connectors.redfox import DAILY_BOARD
    from app.connectors.tikhub_series import CAPABILITY as SERIES_CAP
    from app.connectors.tikhub_series import REQUEST as SERIES_REQUEST

    series_batch = None
    daily_batch = None
    daily_date = (day - timedelta(days=1)).isoformat()
    for snap, rows in pairs:
        if business != "motion_comic" or snap["view_kind"] != "board":
            continue
        job = row(c, "collection_jobs", p.org_id, snap["job_id"])
        if job["capability_code"] == SERIES_CAP and job["safe_request"] == SERIES_REQUEST:
            if series_batch is None or (snap["created_at"], str(snap["id"])) > (
                series_batch[0]["created_at"],
                str(series_batch[0]["id"]),
            ):
                series_batch = (snap, rows)
            continue
        if job["capability_code"] != DAILY_BOARD or job["safe_request"] != {
            "type": "小剧场",
            "startTime": daily_date,
            "endTime": daily_date,
        }:
            continue
        if daily_batch is None or (snap["created_at"], str(snap["id"])) > (
            daily_batch[0]["created_at"],
            str(daily_batch[0]["id"]),
        ):
            daily_batch = (snap, rows)
    if daily_batch is not None:
        ranking = {
            "status": "provider_order",
            "items": sorted(daily_batch[1], key=lambda v: v["entry"]["position"])[:10],
        }
    if series_batch is not None:
        ranking = {
            "status": "series_order",
            "items": sorted(series_batch[1], key=lambda v: v["entry"]["position"])[:10],
        }
    if business == "story_short":
        from app.connectors.douyin_search import CAPABILITY as MICROFILM_CAP
        search_batches = [(snap, rows) for snap, rows in pairs if snap['view_kind'] == 'board' and row(c, 'collection_jobs', p.org_id, snap['job_id'])['capability_code'] == MICROFILM_CAP]
        if search_batches:
            search_batch = max(search_batches, key=lambda v: (v[0]['created_at'], str(v[0]['id'])))
            ranking = {'status': 'provider_order', 'items': sorted(search_batch[1], key=lambda v: v['entry']['position'])[:50]}
    ranked_ids = {v["entry"]["id"] for v in ranking["items"]}
    for value in ranking["items"]:
        value["source_name"] = (
            "微电影 · 抖音综合搜索TOP50"
            if business == "story_short"
            else "TikHub短剧热榜 · content_type=0 · 整剧统计"
            if ranking["status"] == "series_order"
            else f"小剧场 · 红狐每日热门作品榜 · 数据日期 {daily_date}"
            if ranking["status"] == "provider_order"
            else "漫剧关键词作品 · 默认相关性排序"
            if ranking["status"] == "default_order"
            else "漫剧关键词作品 · 已采集候选播放榜"
        )
    original_pairs = pairs + hongguo_pairs
    pairs = [
        (
            snap,
            [v for v in rows if v["entry"]["id"] in ranked_ids]
            if snap["view_kind"] in ranking_kinds
            else rows,
        )
        for snap, rows in pairs
    ]
    lanes = {"board": [], "creator": []}
    boards, creators = {}, {}
    for snap, values in pairs:
        if snap["view_kind"] in ("board", "keyword_works") and values:
            boards[str(snap["source_id"])] = (
                snap["source_id"],
                values[0]["source_name"]
                if values
                else row(c, "sources", p.org_id, snap["source_id"])["name"],
            )
        if snap["view_kind"] not in ("board", "creator_works", "keyword_works"):
            continue  # Discovery is account metadata, never a video or ranking.
        target = "board" if snap["view_kind"] in ("board", "keyword_works") else "creator"
        for value in values:
            if value["entry"]["observation"]["kind"] != "content":
                continue
            lanes[target].append(value)
            if target == "creator" and value["account_id"]:
                creators[str(value["account_id"])] = (value["account_id"], value["author"])
    # Same platform content in multiple sources contributes once per lane, newest observation wins.
    for name, values in lanes.items():
        seen, dedup = set(), []
        for v in sorted(
            values,
            key=lambda x: (x["entry"]["observation"]["observed_at"], str(x["entry"]["id"])),
            reverse=True,
        ):
            key = (
                v["entry"]["observation"]["platform_code"],
                v["entry"]["observation"]["platform_id"],
            )
            if key not in seen:
                seen.add(key)
                dedup.append(v)
        # Keep provider positions within their source; this is not an invented global rank.
        lanes[name] = sorted(
            dedup,
            key=lambda x: (str(x["source_id"]), x["entry"]["position"], str(x["entry"]["id"])),
        )
    # Full-day counts ignore list search/selection; unknown input propagates, exact zero survives.
    all_content = {}
    for v in lanes["board"] + lanes["creator"]:
        obs = v["entry"]["observation"]
        key = (obs["platform_code"], obs["platform_id"])
        if key not in all_content or obs["observed_at"] > all_content[key]["observed_at"]:
            all_content[key] = obs

    def total(field):
        values = [x[field] for x in all_content.values()]
        return (
            str(sum(int(x) for x in values))
            if values and all(x is not None for x in values)
            else None
        )

    has_board = (
        ranking["status"] in ("ready", "default_order", "provider_order", "series_order")
        if business == "motion_comic"
        else any(s["view_kind"] == "board" for s, _ in pairs)
    )
    # Overview is business/day scoped, independent of list lane and catalog.
    has_board = has_board or any(s["view_kind"] == "board" for s, _ in hongguo_pairs)
    board_contents = lanes["board"] + [
        value
        for snap, rows in hongguo_pairs
        if snap["view_kind"] == "board"
        for value in rows
    ]
    video_ids = {
        (v["entry"]["observation"]["platform_code"], v["entry"]["observation"]["platform_id"])
        for v in board_contents
    }
    has_creator = any(s["view_kind"] == "creator_works" for s, _ in pairs)
    metrics = {
        "videos": str(len(video_ids)) if has_board else None,
        "creators": str(len({str(v["account_id"]) for v in lanes["creator"] if v["account_id"]}))
        if has_creator
        else None,
        "comments": total("comment_count"),
        "likes": total("like_count"),
    }
    # Filter before dedup again to keep a content's membership in every board selectable.
    values = []
    candidates = []
    for snap, rows in original_pairs if video_catalog == "hongguo" else pairs:
        if snap["view_kind"] not in (
            ("board", "keyword_works") if lane == "board" else ("creator_works",)
        ):
            continue
        for v in rows:
            obs = v["entry"]["observation"]
            if (source_id and v["source_id"] != source_id) or (
                accounts and str(v["account_id"]) not in accounts
            ):
                continue
            if (
                q
                and q.casefold()
                not in " ".join(
                    str(x or "")
                    for x in (
                        obs["description"],
                        obs["display_name"],
                        v["author"],
                        v["source_name"],
                    )
                ).casefold()
            ):
                continue
            candidates.append(v)
    if video_catalog == "tikhub":
        candidates = [
            v
            for v in candidates
            if series_batch and v["entry"]["snapshot_id"] == series_batch[0]["id"]
        ]
    video_genres = []
    video_subgenres = []
    catalog_has_snapshot = False
    if lane == "board" and video_catalog == "hongguo":
        from app.intelligence.video_filters import filter_hongguo, filter_subgenre

        catalog_rows = [
            value
            for snap, rows in original_pairs
            if snap["view_kind"] in ("board", "keyword_works")
            for value in rows
        ]
        catalog_has_snapshot = bool(filter_hongguo(catalog_rows, None, None)[0])
        scoped_rows, video_genres = filter_hongguo(catalog_rows, video_board, video_genre)
        _, video_subgenres = filter_subgenre(scoped_rows, video_genre, None)
        candidates, _ = filter_hongguo(candidates, video_board, video_genre)
        candidates, _ = filter_subgenre(candidates, video_genre, video_subgenre)
    seen = set()
    for v in sorted(
        candidates,
        key=lambda x: (x["entry"]["observation"]["observed_at"], str(x["entry"]["id"])),
        reverse=True,
    ):
        obs = v["entry"]["observation"]
        key = (obs["platform_code"], obs["platform_id"])
        if key not in seen:
            seen.add(key)
            values.append(v)
    values.sort(key=lambda x: (str(x["source_id"]), x["entry"]["position"], str(x["entry"]["id"])))
    if lane == "creator" and business == "story_short":
        values.sort(key=lambda x: (
            x['entry']['observation']['like_count'] is None,
            -int(x['entry']['observation']['like_count'] or 0),
            -(x['entry']['observation']['published_at'].timestamp() if x['entry']['observation']['published_at'] else 0),
            x['entry']['observation']['platform_id'],
        ))
    if lane == "creator":
        from app.intelligence.creator_samples import sample as creator_sample
        for value in values[(page - 1) * 10 : page * 10]:
            snap = row(c, "intelligence_snapshots", p.org_id, value["entry"]["snapshot_id"])
            obs = row(c, "content_observations", p.org_id, value["entry"]["observation"]["id"])
            content = row(c, "external_contents", p.org_id, obs["content_id"])
            acquired = creator_sample(c, p, snap, content)
            value["comment_sample_count"] = len(acquired) if acquired is not None else None
    if lane == "board" and business == "story_short":
        from app.intelligence.microfilm import sample_for_entry
        for value in values[(page - 1) * 10 : page * 10]:
            acquired = sample_for_entry(c, p, value['entry']['id'], business, day, auth=auth)
            value['comment_sample_count'] = len(acquired) if acquired is not None else None
    if video_catalog == "hongguo":
        from app.intelligence.hongguo import sample_for_content

        if not video_board:
            values.sort(
                key=lambda v: (
                    v.get("heat_value") is None,
                    -int(v.get("heat_value") or 0),
                    v["entry"]["observation"]["platform_id"],
                )
            )
        for value in values[(page - 1) * 10 : page * 10]:
            obs = row(c, "content_observations", p.org_id, value["entry"]["observation"]["id"])
            sample = sample_for_content(c, p, obs["content_id"], business, day, auth=auth)
            value["comment_sample_count"] = len(sample["comments"]) if sample else None

    if (
        lane == "board"
        and video_catalog != "hongguo"
        and ranking["status"] in ("default_order", "provider_order", "series_order")
    ):
        ordering = {v["entry"]["id"]: i for i, v in enumerate(ranking["items"])}
        values.sort(key=lambda x: ordering[x["entry"]["id"]])
    if lane == "board" and video_catalog != "hongguo" and ranking["status"] == "ready":
        values.sort(
            key=lambda x: (
                x["entry"]["observation"]["view_count"] is None,
                -int(x["entry"]["observation"]["view_count"] or 0),
                str(x["entry"]["observation"]["platform_id"]),
            )
        )
    return {
        "video_latest_dates": latest_video_dates(c, p, business, auth=auth),
        "business_code": business,
        "business_date": day,
        "has_snapshot": catalog_has_snapshot if video_catalog == "hongguo" else bool(pairs),
        "metrics": metrics,
        "video_genres": video_genres,
        "video_subgenres": video_subgenres,
        "boards": [{"id": v[0], "name": v[1]} for v in boards.values()],
        "creators": [{"id": v[0], "name": v[1] or "未记录"} for v in creators.values()],
        "page": page,
        "page_size": 10,
        "total": str(len(values)),
        "items": values[(page - 1) * 10 : page * 10],
        "keyword_works_count": str(
            sum(len(rows) for snap, rows in original_pairs if snap["view_kind"] == "keyword_works")
        ),
        "keyword_ranking_status": "not_acquired"
        if video_catalog == "hongguo"
        else ranking["status"],
        "insight": None if video_catalog == "hongguo" else latest_insight(c, p, business, day),
    }
