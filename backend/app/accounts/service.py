"""Explicit installation binding and serialized account lifecycle. No hidden commits."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.accounts.policy import require_administrator
from app.core.config import settings
from app.core.models import metadata
from app.core.repository import VersionConflict, compare_and_swap
from app.security.errors import Denied
from app.security.governance import ROLE_ACTIONS
from app.security.primitives import _derive, digest, hash_password, token, token_hash
from app.security.sessions import Principal, session_view
from app.security.storage import audit, lock_org, receipt

USER_ACTIONS = (
    "content.read",
    "evidence.read",
    "file.read",
    "standard.read",
    "content.write",
    "content.export",
    "research.submit",
    "research.run",
    "task.read",
)
ADMIN_ROLES = ("M", "E", "A", "O")  # Reviewer V remains independently assigned.


def installation(c):
    return c.execute(select(metadata.tables["account_installations"])).mappings().one_or_none()


def access(c):
    if not settings.user_accounts_enabled:
        return {"enabled": False, "setup_required": False, "org_id": None}
    row = installation(c)
    return {
        "enabled": True,
        "setup_required": row is None,
        "org_id": row["org_id"] if row else None,
    }


def require_installation(c, org=None):
    row = installation(c)
    if row is None or (org is not None and row["org_id"] != org):
        raise Denied("AUTH_REQUIRED")
    return row


def member_row(c, org, member_id):
    t = metadata.tables["members"]
    row = (
        c.execute(select(t).where(t.c.org_id == org, t.c.id == member_id)).mappings().one_or_none()
    )
    if not row:
        raise Denied("NOT_FOUND")
    return dict(row)


def user_view(c, p, member_id):
    require_administrator(c, p)
    row = member_row(c, p.org_id, member_id)
    # Disabled members cannot authenticate; derive their assigned role via current grant time.
    return _profile(c, p.org_id, row)


def _admin_assigned(c, org, member):
    return bool(
        c.exec_driver_sql(
            "SELECT 1 FROM grants g JOIN role_actions a ON a.org_id=g.org_id AND a.role_id=g.role_id "
            "WHERE g.org_id=%s AND g.member_id=%s AND g.scope_kind='org' AND g.revoked_at IS NULL "
            "AND (g.expires_at IS NULL OR g.expires_at>clock_timestamp()) "
            "AND a.action_code='member.manage' LIMIT 1",
            (org, member),
        ).scalar()
    )


def _profile(c, org, row):
    return {key: row[key] for key in ("id", "login_name", "display_name", "created_at")} | {
        "role": "administrator" if _admin_assigned(c, org, row["id"]) else "user",
        "enabled": row["disabled_at"] is None,
        "lock_version": str(row["lock_version"]),
    }


def list_users(c, p):
    require_administrator(c, p)
    t = metadata.tables["members"]
    return {
        "items": [
            _profile(c, p.org_id, r)
            for r in c.execute(
                select(t).where(t.c.org_id == p.org_id).order_by(t.c.created_at, t.c.id)
            ).mappings()
        ]
    }


def _roles(c, org):
    t, a = metadata.tables["role_definitions"], metadata.tables["role_actions"]
    result = {}
    for code in (*ADMIN_ROLES, "U"):
        role = c.execute(
            select(t.c.id).where(t.c.org_id == org, t.c.code == code)
        ).scalar_one_or_none()
        if role is None:
            role = uuid4()
            c.execute(t.insert().values(id=role, org_id=org, code=code, name=code))
            for action in USER_ACTIONS if code == "U" else ROLE_ACTIONS[code]:
                c.execute(a.insert().values(org_id=org, role_id=role, action_code=action))
        elif code == "U":
            actual = set(
                c.execute(
                    select(a.c.action_code).where(a.c.org_id == org, a.c.role_id == role)
                ).scalars()
            )
            if actual != set(USER_ACTIONS):
                raise Denied("ACCESS_DENIED")
        result[code] = role
    return result


def _assign(c, org, actor, member, role, *, retain=False):
    roles = _roles(c, org)
    if not retain:
        # A downgraded user must lose custom/configuration grants as well as account roles.
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(), lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s AND revoked_at IS NULL",
            (org, member),
        )
    for code in ADMIN_ROLES if role == "administrator" else ("U",):
        exists = c.exec_driver_sql(
            "SELECT 1 FROM grants WHERE org_id=%s AND member_id=%s AND role_id=%s AND scope_kind='org' AND revoked_at IS NULL AND expires_at IS NULL",
            (org, member, roles[code]),
        ).scalar()
        if not exists:
            c.execute(
                metadata.tables["grants"]
                .insert()
                .values(
                    id=uuid4(),
                    org_id=org,
                    member_id=member,
                    role_id=roles[code],
                    scope_kind="org",
                    granted_by=actor,
                )
            )


def _session(c, org, member):
    row = member_row(c, org, member)
    sid, raw = uuid4(), token()
    now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
    c.execute(
        metadata.tables["auth_sessions"]
        .insert()
        .values(
            id=sid,
            org_id=org,
            member_id=member,
            token_hash=token_hash(raw),
            credential_hash=token_hash(row["password_hash"]),
            created_at=now,
            expires_at=now + timedelta(hours=8),
        )
    )
    return raw, session_view(c, Principal(org, member, sid), raw)


def setup(c, body):
    if not settings.user_accounts_enabled:
        raise Denied("ACCESS_DENIED")
    c.exec_driver_sql("SELECT pg_advisory_xact_lock(634930631)")
    if installation(c):
        raise Denied("ACCESS_DENIED")
    m, o = metadata.tables["members"], metadata.tables["organizations"]
    owner = (
        c.execute(
            select(m)
            .join(o, m.c.org_id == o.c.id)
            .where(o.c.name == "本地单人工作区", m.c.login_name == "__local_owner__")
        )
        .mappings()
        .one_or_none()
    )
    if not owner or owner["disabled_at"] is not None:
        raise Denied("SERVICE_NOT_READY")
    org, member = owner["org_id"], owner["id"]
    lock_org(c, org)
    _unique_login(c, org, body.login_name, member)
    compare_and_swap(
        c,
        "members",
        org,
        member,
        owner["lock_version"],
        {
            "login_name": body.login_name.strip().lower(),
            "display_name": body.display_name.strip(),
            "password_hash": hash_password(body.password),
        },
    )
    _assign(c, org, member, member, "administrator", retain=True)
    c.execute(
        metadata.tables["account_installations"]
        .insert()
        .values(id=1, org_id=org, owner_member_id=member)
    )
    c.exec_driver_sql(
        "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE org_id=%s AND member_id=%s AND revoked_at IS NULL",
        (org, member),
    )
    audit(c, org, member, "accounts.setup", "member", member)
    return _session(c, org, member)


def _unique_login(c, org, name, exclude=None):
    t = metadata.tables["members"]
    q = select(t.c.id).where(t.c.org_id == org, func.lower(t.c.login_name) == name.strip().lower())
    if exclude is not None:
        q = q.where(t.c.id != exclude)
    if c.execute(q).scalar():
        raise Denied("VERSION_CONFLICT")


def _safe_input(body, org, key):
    result = body.model_dump(mode="json", exclude_unset=True)
    if "password" in result:
        result["password"] = _derive(
            result["password"], bytes.fromhex(digest([str(org), str(key)])[:32])
        ).hex()
    return result


def create(c, p, key, body):
    require_administrator(c, p)

    def perform():
        _unique_login(c, p.org_id, body.login_name)
        ident = uuid4()
        c.execute(
            metadata.tables["members"]
            .insert()
            .values(
                id=ident,
                org_id=p.org_id,
                login_name=body.login_name.strip().lower(),
                display_name=body.display_name.strip(),
                password_hash=hash_password(body.password),
            )
        )
        _assign(c, p.org_id, p.member_id, ident, body.role)
        audit(c, p.org_id, p.member_id, "accounts.create", "member", ident, key)
        return {"id": str(ident)}

    ident = receipt(c, p, "createUser", key, _safe_input(body, p.org_id, key), perform)["id"]
    from uuid import UUID

    return user_view(c, p, UUID(ident))


def update(c, p, key, ident, body):
    require_administrator(c, p)

    def perform():
        row = member_row(c, p.org_id, ident)
        if str(row["lock_version"]) != body.expected_version:
            raise Denied("VERSION_CONFLICT")
        if body.enabled is False and ident == p.member_id:
            raise Denied("ACCESS_DENIED")
        if _admin_assigned(c, p.org_id, ident) and (body.role == "user" or body.enabled is False):
            count = c.exec_driver_sql(
                "SELECT count(*) FROM members m WHERE m.org_id=%s AND m.disabled_at IS NULL AND m.id<>%s AND EXISTS(SELECT 1 FROM grants g JOIN role_actions a ON a.org_id=g.org_id AND a.role_id=g.role_id WHERE g.org_id=m.org_id AND g.member_id=m.id AND g.scope_kind='org' AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at>clock_timestamp()) AND a.action_code='member.manage')",
                (p.org_id, ident),
            ).scalar_one()
            if not count:
                raise Denied("ACCESS_DENIED")
        values = {}
        if body.display_name is not None:
            values["display_name"] = body.display_name.strip()
        if body.enabled is not None:
            values["disabled_at"] = (
                None if body.enabled else c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
            )
        if body.password is not None:
            values["password_hash"] = hash_password(body.password)
        try:
            compare_and_swap(c, "members", p.org_id, ident, int(body.expected_version), values)
        except VersionConflict as exc:
            raise Denied("VERSION_CONFLICT") from exc
        if body.role is not None:
            _assign(c, p.org_id, p.member_id, ident, body.role)
        if body.password is not None or body.enabled is False or body.role is not None:
            c.exec_driver_sql(
                "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE org_id=%s AND member_id=%s AND revoked_at IS NULL",
                (p.org_id, ident),
            )
        audit(c, p.org_id, p.member_id, "accounts.update", "member", ident, key)
        return {"id": str(ident)}

    receipt(
        c, p, "updateUser", key, {"member": str(ident), **_safe_input(body, p.org_id, key)}, perform
    )
    return _profile(c, p.org_id, member_row(c, p.org_id, ident))


def register(c, body):
    """Anonymous creation is constrained to the singleton installation and U role."""
    if not settings.user_accounts_enabled:
        raise Denied("ACCESS_DENIED")
    binding = require_installation(c)
    org = binding["org_id"]
    lock_org(c, org)
    _unique_login(c, org, body.email)
    ident = uuid4()
    c.execute(
        metadata.tables["members"]
        .insert()
        .values(
            id=ident,
            org_id=org,
            login_name=body.email,
            display_name=body.display_name.strip()
            if body.display_name
            else body.email.split("@", 1)[0],
            password_hash=hash_password(body.password),
        )
    )
    _assign(c, org, ident, ident, "user")
    audit(c, org, ident, "accounts.register", "member", ident)
    return _session(c, org, ident)
