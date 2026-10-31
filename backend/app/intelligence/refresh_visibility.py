"""Completed channel publication controls display only; immutable snapshots remain addressable."""

from sqlalchemy import text

VISIBLE_SQL = """NOT EXISTS (
 SELECT 1 FROM tasks refresh_child
 WHERE refresh_child.org_id=intelligence_snapshots.org_id
 AND refresh_child.id=(SELECT task_id FROM collection_jobs WHERE id=intelligence_snapshots.job_id AND org_id=intelligence_snapshots.org_id)
 AND refresh_child.idempotency_key LIKE 'refresh/%%'
 AND NOT EXISTS(SELECT 1 FROM audit_events pub
 WHERE pub.org_id=refresh_child.org_id AND pub.action_code='intelligence.refresh.published'
 AND pub.target_id::text=split_part(refresh_child.idempotency_key,'/',2)
 AND pub.safe_details->>'code'=split_part(refresh_child.idempotency_key,'/',3))
)"""


def visible_snapshots():
    return text(VISIBLE_SQL.replace("%%", "%"))
