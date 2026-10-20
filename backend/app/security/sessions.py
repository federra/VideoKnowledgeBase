"""Persistent opaque sessions. Roles and grants are re-read on every operation."""

import hmac
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.models import metadata
from app.security.errors import Denied
from app.security.primitives import digest, token, token_hash, verify_password
from app.security.storage import audit, lock_org


@dataclass(frozen=True)
class MemberPrincipal:
    """Server-only task actor: current membership, never a borrowed browser session."""

    org_id: UUID
    member_id: UUID


@dataclass(frozen=True)
class Principal:
    org_id: UUID
    member_id: UUID
    session_id: UUID


def csrf_for(raw):
    return hmac.new(raw.encode(), b"cip:csrf:v1", "sha256").hexdigest()


def valid_csrf(raw, value):
    return (isinstance(value, str) and len(value) == 64 and value.isascii()
            and hmac.compare_digest(csrf_for(raw), value))


def limit_login(engine, org, name, client):
    # The counting transaction commits even for unknown organizations and failed login.
    buckets = {digest(["account", str(org), name.lower()]): 5, digest(["client", client]): 30}
    denied = False
    with engine.begin() as c:
        for bucket, maximum in sorted(buckets.items()):
            count = c.exec_driver_sql(
                """INSERT INTO auth_rate_limits(bucket,window_start,attempts)
                VALUES (%s,clock_timestamp(),1) ON CONFLICT (bucket) DO UPDATE SET
                attempts=CASE WHEN auth_rate_limits.window_start < clock_timestamp()-interval '10 minutes'
                  THEN 1 ELSE auth_rate_limits.attempts+1 END,
                window_start=CASE WHEN auth_rate_limits.window_start < clock_timestamp()-interval '10 minutes'
                  THEN clock_timestamp() ELSE auth_rate_limits.window_start END RETURNING attempts""",
                (bucket,),
            ).scalar_one()
            denied |= count > maximum
    if denied:
        raise Denied("RATE_LIMITED")


def login(engine, org, name, password, client, *, request_id=None):
    limit_login(engine, org, name, client)
    members = metadata.tables["members"]
    # KDF occurs outside tenant locks; recheck exact credential under the lock afterwards.
    with engine.connect() as c:
        row = (
            c.execute(
                select(members).where(
                    members.c.org_id == org, func.lower(members.c.login_name) == name.lower()
                )
            )
            .mappings()
            .one_or_none()
        )
    valid = verify_password(password, row["password_hash"] if row else None)
    with engine.begin() as c:
        lock_org(c, org)
        current = (
            (
                c.execute(select(members).where(members.c.id == row["id"], members.c.org_id == org))
                .mappings()
                .one_or_none()
            )
            if row
            else None
        )
        valid = (
            valid
            and current
            and current["disabled_at"] is None
            and current["password_hash"] == row["password_hash"]
        )
        if not valid:
            # Unknown organizations have no valid FK/audit tenant; existing org attempts
            # are recorded without account identifiers or supplied credential material.
            if c.exec_driver_sql("SELECT 1 FROM organizations WHERE id=%s", (org,)).scalar():
                audit(c, org, None, "session.login_failed", "session", request_id=request_id)
        else:
            raw = token()
            now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
            sid = uuid4()
            c.execute(
                metadata.tables["auth_sessions"]
                .insert()
                .values(
                    id=sid,
                    org_id=org,
                    member_id=current["id"],
                    token_hash=token_hash(raw),
                    credential_hash=token_hash(current["password_hash"]),
                    created_at=now,
                    expires_at=now + timedelta(hours=8),
                )
            )
            audit(c, org, current["id"], "session.login", "session", sid, request_id)
            payload = session_view(c, Principal(org, current["id"], sid), raw)
    if not valid:
        raise Denied("AUTH_INVALID")
    return raw, payload


def refresh(c, p, *, allow_revoked=False):
    lock_org(c, p.org_id)
    if isinstance(p, MemberPrincipal):
        m = metadata.tables["members"]
        row = c.execute(select(m).where(
            m.c.org_id == p.org_id, m.c.id == p.member_id,
            m.c.disabled_at.is_(None))).mappings().one_or_none()
        if not row:
            raise Denied("AUTH_REQUIRED")
        return row
    s, m = metadata.tables["auth_sessions"], metadata.tables["members"]
    row = (
        c.execute(
            select(s, m.c.disabled_at, m.c.password_hash, m.c.display_name)
            .join(m, (s.c.org_id == m.c.org_id) & (s.c.member_id == m.c.id))
            .where(
                s.c.id == p.session_id,
                s.c.org_id == p.org_id,
                s.c.member_id == p.member_id,
                (True if allow_revoked else s.c.revoked_at.is_(None)),
                s.c.expires_at > func.clock_timestamp(),
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        not row
        or row["disabled_at"] is not None
        or not row["password_hash"]
        or row["credential_hash"] != token_hash(row["password_hash"])
    ):
        raise Denied("AUTH_REQUIRED")
    return row


def authenticate(c, raw, *, allow_revoked=False):
    if not raw or len(raw) != 43:
        raise Denied("AUTH_REQUIRED")
    t = metadata.tables["auth_sessions"]
    row = c.execute(select(t).where(t.c.token_hash == token_hash(raw))).mappings().one_or_none()
    if not row:
        raise Denied("AUTH_REQUIRED")
    p = Principal(row["org_id"], row["member_id"], row["id"])
    refresh(c, p, allow_revoked=allow_revoked)
    return p


def active_grants(c, p):
    refresh(c, p)
    g, a = metadata.tables["grants"], metadata.tables["role_actions"]
    return (
        c.execute(
            select(g, a.c.action_code)
            .join(a, (g.c.org_id == a.c.org_id) & (g.c.role_id == a.c.role_id))
            .where(
                g.c.org_id == p.org_id,
                g.c.member_id == p.member_id,
                g.c.revoked_at.is_(None),
                (g.c.expires_at.is_(None) | (g.c.expires_at > func.clock_timestamp())),
            )
        )
        .mappings()
        .all()
    )


def session_view(c, p, raw):
    row = refresh(c, p)
    version = c.exec_driver_sql(
        "SELECT authz_version FROM organizations WHERE id=%s", (p.org_id,)
    ).scalar_one()
    return {
        "org_id": p.org_id,
        "member_id": p.member_id,
        "display_name": row["display_name"],
        "authz_version": str(version),
        "csrf_token": csrf_for(raw),
        "expires_at": row["expires_at"],
        "actions": sorted({g["action_code"] for g in active_grants(c, p)}),
    }


def logout(c, raw, csrf, *, request_id=None):
    p = authenticate(c, raw, allow_revoked=True)
    if not valid_csrf(raw, csrf):
        raise Denied("CSRF_INVALID")
    changed = c.exec_driver_sql(
        "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s AND revoked_at IS NULL",
        (p.session_id,),
    ).rowcount
    if changed:
        audit(c, p.org_id, p.member_id, "session.logout", "session", p.session_id, request_id)
