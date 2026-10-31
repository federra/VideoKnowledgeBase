"""Read first-episode comment evidence from the exact creator snapshot task."""

import json

from app.connectors.douyin_series import comments, first_episode
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.errors import Denied


def sample(c, p, snapshot, content):
    job = row(c, "collection_jobs", p.org_id, snapshot["job_id"])
    if job["capability_code"] != "douyin.creator.series":
        return None
    found, captured = browser_sample(c, p, snapshot, content)
    if found:
        return captured
    az = Authorizer(c, p)
    az.read("sources", snapshot["source_id"])
    candidates = (
        c.exec_driver_sql(
            "SELECT t.id,r.body_text FROM tasks t JOIN task_outputs o ON o.org_id=t.org_id AND o.task_id=t.id JOIN raw_assets r ON r.org_id=o.org_id AND r.id=o.raw_asset_id WHERE t.org_id=%s AND t.source_id=%s AND o.role='creator_series_manifest'",
            (p.org_id, snapshot["source_id"]),
        )
        .mappings()
        .all()
    )
    matches = [
        r["id"]
        for r in candidates
        if json.loads(r["body_text"]).get("snapshot") == str(snapshot["id"])
    ]
    if len(matches) != 1:
        raise Denied("SOURCE_UNAVAILABLE")
    task = row(c, "tasks", p.org_id, matches[0])
    if task["state"] != "succeeded":
        raise Denied("SOURCE_UNAVAILABLE")
    raw_id = c.exec_driver_sql(
        "SELECT raw_asset_id FROM task_outputs WHERE org_id=%s AND task_id=%s AND role='creator_series_manifest'",
        (p.org_id, task["id"]),
    ).scalar_one()
    raw = az.read("raw_assets", raw_id)
    data = json.loads(raw["body_text"])
    if data["snapshot"] != str(snapshot["id"]):
        raise Denied("SOURCE_UNAVAILABLE")
    sid = content["platform_content_id"].split(":", 1)[1]
    match = next((s for s in data["samples"] if s["series_id"] == sid), None)
    if match is None:
        if sid in data.get("unavailable", []):
            return None
        raise Denied("SOURCE_UNAVAILABLE")
    from uuid import UUID

    ep = az.read("raw_assets", UUID(match["episode_raw"]))
    evidence = az.read("raw_assets", UUID(match["raw"]))
    for r in [ep, evidence]:
        if (
            r["collection_job_id"] != job["id"]
            or shanghai_date(r["captured_at"]) != snapshot["business_date"]
        ):
            raise Denied("SOURCE_UNAVAILABLE")
    aid = first_episode(json.loads(ep["body_text"]), sid, job["safe_request"]["uid"])
    expected = comments(json.loads(evidence["body_text"]), aid)
    values = (
        c.exec_driver_sql(
            "SELECT * FROM comment_evidence WHERE org_id=%s AND raw_asset_id=%s ORDER BY sample_position",
            (p.org_id, evidence["id"]),
        )
        .mappings()
        .all()
    )
    if (
        aid != match["aweme_id"]
        or len(values) != len(expected)
        or any(v["content_id"] != content["id"] for v in values)
    ):
        raise Denied("SOURCE_UNAVAILABLE")
    fields = (
        "id",
        "created_at",
        "content_id",
        "platform_comment_id",
        "body_text",
        "username",
        "like_count",
        "posted_at_raw",
        "posted_at",
        "captured_at",
    )
    return [
        {k: str(v[k]) if k == "like_count" and v[k] is not None else v[k] for k in fields}
        for v in values
    ]


def browser_sample(c, p, snapshot, content):
    from uuid import UUID

    from app.collection.creator_browser_comments import KIND, ROLE, bundle_from_capture
    from app.tasks.service import TaskError

    candidates = (
        c.exec_driver_sql(
            "SELECT t.id,t.state,r.id AS raw_id,r.body_text,i.body_text AS selection_text FROM tasks t JOIN task_outputs o ON o.org_id=t.org_id AND o.task_id=t.id JOIN raw_assets r ON r.org_id=o.org_id AND r.id=o.raw_asset_id JOIN raw_assets i ON i.org_id=t.org_id AND i.id=t.raw_asset_id WHERE t.org_id=%s AND t.source_id=%s AND t.kind IN (%s,'creator.browser.reparse') AND o.role=%s ORDER BY t.created_at DESC,t.id DESC",
            (p.org_id, snapshot["source_id"], KIND, ROLE),
        )
        .mappings()
        .all()
    )
    entry = next(
        (
            r
            for r in candidates
            if json.loads(r["body_text"]).get("snapshot") == str(snapshot["id"])
            and any(
                t["content"] == str(content["id"])
                for t in json.loads(r["selection_text"])["targets"]
            )
        ),
        None,
    )
    if entry is None:
        return False, None
    az = Authorizer(c, p)
    az.read("sources", snapshot["source_id"])
    if entry["state"] != "succeeded":
        raise Denied("SOURCE_UNAVAILABLE")
    az.read("raw_assets", entry["raw_id"])
    manifest = json.loads(entry["body_text"])
    chosen = next((r for r in manifest["captures"] if r["content"] == str(content["id"])), None)
    if not chosen or chosen["status"] != "sampled":
        return True, None
    raw = az.read("raw_assets", UUID(chosen["raw"]))
    data = json.loads(raw["body_text"])
    job = row(c, "collection_jobs", p.org_id, snapshot["job_id"])
    if (
        raw["processing_task_id"] != entry["id"]
        or raw["external_content_id"] != content["id"]
        or data["snapshot_id"] != str(snapshot["id"])
        or data["uid"] != job["safe_request"]["uid"]
        or "series:" + data["series_id"] != content["platform_content_id"]
        or shanghai_date(raw["captured_at"]) != snapshot["business_date"]
    ):
        raise Denied("SOURCE_UNAVAILABLE")
    try:
        expected = bundle_from_capture(data)["comments"]
    except TaskError:
        raise Denied("SOURCE_UNAVAILABLE") from None
    values = (
        c.exec_driver_sql(
            "SELECT * FROM comment_evidence WHERE org_id=%s AND raw_asset_id=%s ORDER BY sample_position",
            (p.org_id, raw["id"]),
        )
        .mappings()
        .all()
    )
    if len(values) != len(expected) or any(
        v["content_id"] != content["id"] or any(v[k] != e[k] for k in e)
        for v, e in zip(values, expected, strict=True)
    ):
        raise Denied("SOURCE_UNAVAILABLE")
    fields = (
        "id",
        "created_at",
        "content_id",
        "platform_comment_id",
        "body_text",
        "username",
        "like_count",
        "posted_at_raw",
        "posted_at",
        "captured_at",
    )
    return True, [
        {k: str(v[k]) if k == "like_count" and v[k] is not None else v[k] for k in fields}
        for v in values
    ]
