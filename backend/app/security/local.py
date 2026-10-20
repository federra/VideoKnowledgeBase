"""Explicit loopback-only single-user entry. Never bypasses object authorization."""

from datetime import timedelta
from secrets import token_urlsafe

from sqlalchemy import select

from app.core.models import metadata
from app.security.errors import Denied
from app.security.governance import bootstrap
from app.security.primitives import token, token_hash
from app.security.sessions import Principal, authenticate, session_view
from app.security.storage import audit


def check_local(request):
    if (
        request.url.hostname not in ("127.0.0.1", "localhost")
        or not request.client
        or request.client.host not in ("127.0.0.1", "::1")
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise Denied("ACCESS_DENIED")
    from app.core.config import settings
    from app.security.primitives import check_origin

    origin = request.headers.get("origin")
    if origin and not check_origin(origin, settings.allowed_origins):
        raise Denied("CSRF_INVALID")


def enter(c, raw=None):
    # Serialize first-open and avoid choosing an arbitrary existing organization/user.
    c.exec_driver_sql("SELECT pg_advisory_xact_lock(634930631)")
    m, o = metadata.tables["members"], metadata.tables["organizations"]
    row = (
        c.execute(
            select(m)
            .join(o, m.c.org_id == o.c.id)
            .where(o.c.name == "本地单人工作区", m.c.login_name == "__local_owner__")
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        org, member = bootstrap(c, "本地单人工作区", "__local_owner__", token_urlsafe(40))
        from app.core.repository import compare_and_swap

        compare_and_swap(c, "members", org, member, 1, {"display_name": "南哥"})
        for code in ("E", "O"):
            role = c.exec_driver_sql(
                "SELECT id FROM role_definitions WHERE org_id=%s AND code=%s", (org, code)
            ).scalar_one()
            c.exec_driver_sql(
                "INSERT INTO grants(id,org_id,member_id,role_id,scope_kind,granted_by) VALUES (gen_random_uuid(),%s,%s,%s,'org',%s)",
                (org, member, role, member),
            )
        row = c.execute(select(m).where(m.c.id == member)).mappings().one()
    if row["disabled_at"] is not None:
        raise Denied("AUTH_REQUIRED")
    if raw:
        try:
            p = authenticate(c, raw)
            if p.org_id == row["org_id"] and p.member_id == row["id"]:
                return raw, session_view(c, p, raw)
        except Denied:
            pass
    now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
    from uuid import uuid4

    sid, raw = uuid4(), token()
    c.execute(
        metadata.tables["auth_sessions"]
        .insert()
        .values(
            id=sid,
            org_id=row["org_id"],
            member_id=row["id"],
            token_hash=token_hash(raw),
            credential_hash=token_hash(row["password_hash"]),
            created_at=now,
            expires_at=now + timedelta(hours=8),
        )
    )
    audit(c, row["org_id"], row["id"], "local.entry", "session", sid)
    return raw, session_view(c, Principal(row["org_id"], row["id"], sid), raw)
