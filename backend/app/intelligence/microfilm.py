"""Read exact microfilm comment provenance; never acquire or analyze on GET."""

import json

from app.collection.microfilm import comment_rows, saved
from app.connectors import douyin_search as ds
from app.intelligence.service import row
from app.security.errors import Denied
from app.security.read_authorizer import ReadAuthorizer


def saved_for_read(c, p, job, az):
    return az.memo(("microfilm.saved", job["id"]), lambda: saved(c, p.org_id, job, az))


def material(c, p, snap, job, az):
    az.read("sources", snap["source_id"])
    task = az.read("tasks", job["task_id"])
    if task["state"] != "succeeded":
        raise Denied("SOURCE_UNAVAILABLE")
    manifest_id = c.exec_driver_sql(
        "SELECT raw_asset_id FROM task_outputs WHERE org_id=%s AND task_id=%s AND role='microfilm_manifest'",
        (p.org_id, task["id"]),
    ).scalar_one()
    manifest = json.loads(az.read("raw_assets", manifest_id)["body_text"])
    if manifest["snapshot"] != str(snap["id"]):
        raise Denied("SOURCE_UNAVAILABLE")
    pages, _, samples, _ = saved_for_read(c, p, job, az)
    batch, _ = ds.combine(pages)
    return manifest, samples, {r["platform_content_id"] for r in batch.records}


def sample_for_entry(c, p, entry_id, business, day, *, auth=None):
    entry = row(c, "snapshot_entries", p.org_id, entry_id)
    snap = row(c, "intelligence_snapshots", p.org_id, entry["snapshot_id"])
    if snap["business_code"] != business or snap["business_date"] != day or not snap["sealed_at"]:
        raise Denied("NOT_FOUND")
    job = row(c, "collection_jobs", p.org_id, snap["job_id"])
    if job["capability_code"] != ds.CAPABILITY:
        return None
    az = auth or ReadAuthorizer(c, p)
    obs = row(c, "content_observations", p.org_id, entry["content_observation_id"])
    az.read("raw_assets", obs["raw_asset_id"])
    content = row(c, "external_contents", p.org_id, obs["content_id"])
    aid = content["platform_content_id"]
    manifest, samples, content_ids = az.memo(
        ("microfilm.material", snap["id"]), lambda: material(c, p, snap, job, az)
    )
    if aid not in manifest["comments"]:
        return None
    if aid not in content_ids:
        raise Denied("SOURCE_UNAVAILABLE")
    acquired = samples.get(aid, [])
    if [str(r["id"]) for r, _ in acquired] != manifest["comments"][aid]:
        raise Denied("SOURCE_UNAVAILABLE")
    expected = comment_rows(acquired, aid)
    values = []
    for raw in {r["id"]: r for r, _ in expected}.values():
        values.extend(
            c.exec_driver_sql(
                "SELECT * FROM comment_evidence WHERE org_id=%s AND raw_asset_id=%s ORDER BY sample_position",
                (p.org_id, raw["id"]),
            )
            .mappings()
            .all()
        )
    if len(values) != len(expected) or any(v["content_id"] != content["id"] for v in values):
        raise Denied("SOURCE_UNAVAILABLE")
    # Valid empty sample has no comment rows but keeps its successful request evidence.
    if not expected and manifest["comment_counts"][aid] != 0:
        raise Denied("SOURCE_UNAVAILABLE")
    return [
        {
            k: (str(v[k]) if k == "like_count" and v[k] is not None else v[k])
            for k in (
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
        }
        for v in values
    ]
