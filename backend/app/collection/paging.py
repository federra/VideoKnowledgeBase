"""Short-lived, current-authority bound cursors; restart invalidates local dev cursors."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime
from uuid import UUID

from app.security.errors import Denied

KEY = secrets.token_bytes(32)


def page(c, p, data, *, kind, business, limit=20, cursor=None, q=None):
    version = c.exec_driver_sql(
        "SELECT authz_version FROM organizations WHERE id=%s", (p.org_id,)
    ).scalar_one()
    scope = {
        "org": str(p.org_id),
        "member": str(p.member_id),
        "authz": str(version),
        "kind": kind,
        "business": business,
        "q": q,
        "limit": limit,
    }
    after = None
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode())
            body, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.digest(KEY, body, hashlib.sha256)):
                raise ValueError()
            value = json.loads(body)
            if (
                value["scope"] != scope
                or value["until"] < time.time()
                or not isinstance(value["after"], list)
                or len(value["after"]) != 2
            ):
                raise ValueError()
            after = (datetime.fromisoformat(value["after"][0]), UUID(value["after"][1]).int)
            if after[0].tzinfo is None:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise Denied("CURSOR_EXPIRED") from None
    items = data["items"]
    if q:
        items = [
            row
            for row in items
            if q.casefold() in (row.get("name") or row.get("kind") or "").casefold()
        ]
    total = len(items)
    if after is not None:
        items = [
            row
            for row in items
            if (datetime.fromisoformat(row["created_at"]), UUID(row["id"]).int) < after
        ]
    selected = items[:limit]
    following = None
    if len(items) > limit:
        last = selected[-1]
        body = json.dumps(
            {
                "scope": scope,
                "after": [last["created_at"], last["id"]],
                "until": int(time.time()) + 300,
            },
            sort_keys=True,
        ).encode()
        following = base64.urlsafe_b64encode(body + hmac.digest(KEY, body, hashlib.sha256)).decode()
    return {"items": selected, "next_cursor": following, "total": str(total)}
