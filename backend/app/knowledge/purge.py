"""Permanent knowledge-payload erasure; historical IDs and reports remain stable."""

import logging

from sqlalchemy.exc import DBAPIError

from app.core.repository import VersionConflict
from app.knowledge.recycle import editable, require_business_edit
from app.security.authorization import Authorizer
from app.security.sessions import refresh
from app.security.storage import lock_org, receipt


def purge(c, p, key, body):
    lock_org(c, p.org_id)
    refresh(c, p)
    az = Authorizer(c, p, include_recycled=True)
    rows = {}
    for item in body.items:
        row = az.row("knowledge_items", item.id)
        if row.get("purged_at"):
            # An exact receipt may be replayed after erasure, but current shared
            # business and source access are still required. Never return payload.
            require_business_edit(c, p, az, item.id)
            refs = (
                c.exec_driver_sql(
                    "SELECT DISTINCT e.evidence_id FROM knowledge_evidence e JOIN knowledge_revisions r ON r.org_id=e.org_id AND r.id=e.revision_id WHERE r.org_id=%s AND r.knowledge_id=%s",
                    (p.org_id, item.id),
                )
                .scalars()
                .all()
            )
            for eid in refs:
                az.read("evidence_refs", eid)
        else:
            row = editable(c, p, az, item.id)
        rows[item.id] = row

    def perform():
        for item in body.items:
            row = rows[item.id]
            if (
                row.get("purged_at")
                or not row["recycled_at"]
                or str(row["lock_version"]) != item.expected_lock_version
            ):
                raise VersionConflict("VERSION_CONFLICT")
        for item in body.items:
            done = c.exec_driver_sql(
                "SELECT cip_purge_knowledge(%s,%s,%s,%s,false)",
                (p.org_id, item.id, int(item.expected_lock_version), p.member_id),
            ).scalar_one()
            if not done:
                raise VersionConflict("VERSION_CONFLICT")
        return {"ids": [str(item.id) for item in body.items]}

    return receipt(c, p, "purgeKnowledge", key, body.model_dump(mode="json"), perform)


def cleanup_expired(engine, limit=50, *, scan_cursor=None):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Retention batch must contain 1..500 items")
    cursor = scan_cursor if scan_cursor is not None else {}
    after = cursor.get("after")
    with engine.connect() as c:

        def fetch(position):
            clause = " AND (recycled_at,org_id,id)>(%s,%s,%s)" if position else ""
            return (
                c.exec_driver_sql(
                    "SELECT org_id,id,lock_version,recycled_at FROM knowledge_items "
                    "WHERE recycled_at+interval '720 hours'<=clock_timestamp() AND purged_at IS NULL"
                    + clause
                    + " ORDER BY recycled_at,org_id,id LIMIT %s",
                    (*position, limit) if position else (limit,),
                )
                .mappings()
                .all()
            )

        due = fetch(after)
        if not due and after:
            cursor.clear()
            due = fetch(None)
    count = 0
    for row in due:
        try:
            with engine.begin() as c:
                c.exec_driver_sql("SET LOCAL lock_timeout='2s'")
                c.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                count += bool(
                    c.exec_driver_sql(
                        "SELECT cip_purge_knowledge(%s,%s,%s,NULL,true)",
                        (row["org_id"], row["id"], row["lock_version"]),
                    ).scalar_one()
                )
        except DBAPIError as exc:
            # Roll back only this item; rotating the cursor also prevents a full
            # failing batch from starving later organizations on the next tick.
            logging.getLogger(__name__).warning(
                "knowledge retention item deferred error_type=%s", type(exc).__name__
            )
        finally:
            cursor["after"] = (row["recycled_at"], row["org_id"], row["id"])
    return count
