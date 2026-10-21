"""Read an acquired, unanalyzed comment sample without fabricating an AI feedback report."""

from app.connectors.hongguo import VERSION, parse_comments
from app.core.models import metadata
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.errors import Denied


def sample_for_content(c, p, content_id, business, day):
    raw = (
        c.exec_driver_sql(
            "SELECT r.* FROM raw_assets r JOIN collection_jobs j ON j.org_id=r.org_id AND j.id=r.collection_job_id "
            "JOIN sources s ON s.org_id=j.org_id AND s.id=j.source_id JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id "
            "JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id "
            "JOIN task_outputs o ON o.org_id=t.org_id AND o.task_id=t.id AND o.raw_asset_id=r.id AND o.role='hongguo_comment_sample' "
            "WHERE r.org_id=%s AND s.content_id=%s AND s.platform_code='hongguo' AND j.business_code=%s "
            "AND j.business_date=%s AND j.capability_code='hongguo.comments' AND j.connector_version=%s "
            "AND t.state='succeeded' AND cc.outcome='success' ORDER BY r.captured_at DESC,r.id DESC LIMIT 1",
            (p.org_id, content_id, business, day, VERSION),
        )
        .mappings()
        .one_or_none()
    )
    if raw is None:
        return None
    az = Authorizer(c, p)
    try:
        az.read("raw_assets", raw["id"])
        job = row(c, "collection_jobs", p.org_id, raw["collection_job_id"])
        # A sample retains the original board dependency even if displayed in another board.
        deps = (
            c.exec_driver_sql(
                "SELECT s.id,s.source_id,o.raw_asset_id FROM task_inputs i JOIN intelligence_snapshots s "
                "ON s.org_id=i.org_id AND s.id=i.snapshot_id JOIN snapshot_entries e ON e.org_id=s.org_id AND e.snapshot_id=s.id "
                "JOIN content_observations o ON o.org_id=e.org_id AND o.id=e.content_observation_id "
                "WHERE i.org_id=%s AND i.task_id=%s AND o.content_id=%s AND s.sealed_at IS NOT NULL "
                "AND s.business_code=%s AND s.business_date=%s",
                (p.org_id, job["task_id"], content_id, business, day),
            )
            .mappings()
            .all()
        )
        if len(deps) != 1:
            raise Denied("SOURCE_UNAVAILABLE")
        az.read("sources", deps[0]["source_id"])
        az.read("raw_assets", deps[0]["raw_asset_id"])
    except Denied as exc:
        if exc.code == "NOT_FOUND":
            return None  # Never fall back to older or withdrawn evidence.
        raise
    if shanghai_date(raw["captured_at"]) != day:
        raise Denied("SOURCE_UNAVAILABLE")
    data = parse_comments(raw["body_text"], job["safe_request"]["series_id"])
    table = metadata.tables["comment_evidence"]
    values = (
        c.execute(
            table.select()
            .where(table.c.org_id == p.org_id, table.c.raw_asset_id == raw["id"])
            .order_by(table.c.sample_position)
        )
        .mappings()
        .all()
    )
    if len(values) != len(data["comments"]) or any(v["content_id"] != content_id for v in values):
        raise Denied("SOURCE_UNAVAILABLE")
    data["comments"] = [
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
    return data
