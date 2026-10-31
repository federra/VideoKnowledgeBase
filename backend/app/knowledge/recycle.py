"""Atomic, versioned recycling and restore within the 30-day retention window."""

from datetime import timedelta

from sqlalchemy import func

from app.core.repository import VersionConflict, compare_and_swap
from app.knowledge import service
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt


def require_business_edit(c, p, az, kid):
    # A stable knowledge item may be shared by several businesses or candidates.
    codes = (
        c.exec_driver_sql(
            "SELECT DISTINCT b.business_code FROM knowledge_businesses b JOIN knowledge_revisions r ON r.org_id=b.org_id AND r.id=b.revision_id WHERE r.org_id=%s AND r.knowledge_id=%s",
            (p.org_id, kid),
        )
        .scalars()
        .all()
    )
    if not codes or not all(
        az.allowed(
            "knowledge.edit", {("org", str(p.org_id)), ("knowledge", str(kid)), ("business", code)}
        )
        for code in codes
    ):
        raise Denied("ACCESS_DENIED")


def editable(c, p, az, kid):
    row = az.read("knowledge_items", kid)
    require_business_edit(c, p, az, kid)
    return row


def change(c, p, key, body, *, restore=False):
    lock_org(c, p.org_id)
    refresh(c, p)
    az = Authorizer(c, p, include_recycled=True)
    rows = {item.id: editable(c, p, az, item.id) for item in body.items}

    def perform():
        now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
        # Validate the entire batch before changing the first row.
        for item in body.items:
            row = rows[item.id]
            if (
                str(row["lock_version"]) != item.expected_lock_version
                or bool(row["recycled_at"]) != restore
                or restore and row["recycled_at"] + timedelta(days=30) <= now
            ):
                raise VersionConflict("VERSION_CONFLICT")
        for item in body.items:
            compare_and_swap(
                c,
                "knowledge_items",
                p.org_id,
                item.id,
                int(item.expected_lock_version),
                {
                    "recycled_at": None if restore else func.clock_timestamp(),
                    "recycled_by": None if restore else p.member_id,
                },
            )
            audit(
                c,
                p.org_id,
                p.member_id,
                "knowledge.restored" if restore else "knowledge.recycled",
                "knowledge",
                item.id,
                key,
            )
        return {"ids": [str(item.id) for item in body.items]}

    return receipt(
        c,
        p,
        "restoreKnowledge" if restore else "recycleKnowledge",
        key,
        body.model_dump(mode="json"),
        perform,
    )


def listing(c, p, business, *, q=None, category=None):
    refresh(c, p)
    az = Authorizer(c, p, include_recycled=True)
    ids = (
        c.exec_driver_sql(
            "SELECT id FROM knowledge_items WHERE org_id=%s AND recycled_at IS NOT NULL AND purged_at IS NULL AND recycled_at+interval '720 hours'>clock_timestamp() ORDER BY recycled_at DESC,id DESC",
            (p.org_id,),
        )
        .scalars()
        .all()
    )
    items = []
    for kid in ids:
        try:
            editable(c, p, az, kid)
            item = service.detail(c, p, kid, az=az)
        except Denied as exc:
            if exc.code in ("NOT_FOUND", "ACCESS_DENIED"):
                continue
            raise
        if business not in item["business_codes"] or (
            category and item["browse_category"] != category
        ):
            continue
        if q and service.normalize(q) not in service.normalize(
            item["title"] + " " + item["revision"]["body_text"] + " " + str(kid)
        ):
            continue
        items.append(item)
    return {"items": items, "next_cursor": None, "total": str(len(items))}
