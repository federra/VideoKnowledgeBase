"""Controlled onboarding and session-authorized governance; no implicit admin bypass."""

from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.models import SCOPE_SLOTS, metadata
from app.core.repository import compare_and_swap
from app.security.errors import Denied
from app.security.primitives import _derive, digest, hash_password
from app.security.sessions import active_grants
from app.security.storage import audit, lock_org, receipt

ADMIN_ACTIONS = ["member.manage", "role.manage", "grant.manage", "audit.read"]
# Derived directly from the action matrix in 数据字典-权限与状态.md.
ROLE_ACTIONS = {code: [] for code in "REVAOM"}
for action, roles in {
    "content.read": "REVA",
    "evidence.read": "REVA",
    "file.read": "REVA",
    "content.export": "EA",
    "content.write": "EA",
    "research.submit": "EA",
    "research.run": "A",
    "knowledge.candidate.read": "EVA",
    "knowledge.edit": "EA",
    "knowledge.review.run": "EVA",
    "report.review.run": "VA",
    "knowledge.review": "V",
    "knowledge.publish": "V",
    "report.review": "VA",
    "evaluation.review": "VA",
    "prediction.edit": "A",
    "prediction.freeze": "A",
    "prediction.retract": "A",
    "standard.read": "REVAO",
    "standard.edit": "AO",
    "standard.approve": "V",
    "standard.activate": "O",
    "source.configure": "O",
    "collection.run": "O",
    "model.configure": "O",
    "task.read": "EVAO",
    "task.manage": "AO",
    "member.manage": "M",
    "role.manage": "M",
    "grant.manage": "M",
    "audit.read": "M",
}.items():
    for code in roles:
        ROLE_ACTIONS[code].append(action)


def bootstrap(c, org_name, login_name, password):
    if not org_name.strip() or not login_name.strip():
        raise ValueError("Organization and login must be nonempty.")
    org, member, role = uuid4(), uuid4(), uuid4()
    c.execute(metadata.tables["organizations"].insert().values(id=org, name=org_name))
    lock_org(c, org)
    c.execute(
        metadata.tables["members"]
        .insert()
        .values(
            id=member,
            org_id=org,
            login_name=login_name,
            display_name=login_name,
            password_hash=hash_password(password),
        )
    )
    for code, actions in ROLE_ACTIONS.items():
        role_id = role if code == "M" else uuid4()
        c.execute(
            metadata.tables["role_definitions"]
            .insert()
            .values(id=role_id, org_id=org, code=code, name=code)
        )
        for action in actions:
            c.execute(
                metadata.tables["role_actions"]
                .insert()
                .values(org_id=org, role_id=role_id, action_code=action)
            )
    c.execute(
        metadata.tables["grants"]
        .insert()
        .values(
            id=uuid4(),
            org_id=org,
            member_id=member,
            role_id=role,
            scope_kind="org",
            granted_by=member,
        )
    )
    audit(c, org, member, "organization.bootstrap", "organization", org)
    return org, member


def org_action(c, p, action):
    if not any(
        g["action_code"] == action and g["scope_kind"] == "org" for g in active_grants(c, p)
    ):
        raise Denied("ACCESS_DENIED")


def create_member(c, p, key, login_name, display_name, password):
    lock_org(c, p.org_id)
    org_action(c, p, "member.manage")
    if not login_name.strip() or not display_name.strip() or not 15 <= len(password) <= 1024:
        raise Denied("VALIDATION_FAILED")
    payload = {
        "login": login_name,
        "display": display_name,
        "credential": _derive(
            password, bytes.fromhex(digest([str(p.org_id), str(key)])[:32])
        ).hex(),
    }

    def perform():
        ident = uuid4()
        credential = hash_password(password)
        org_action(c, p, "member.manage")
        c.execute(
            metadata.tables["members"]
            .insert()
            .values(
                id=ident,
                org_id=p.org_id,
                login_name=login_name,
                display_name=display_name,
                password_hash=credential,
            )
        )
        audit(c, p.org_id, p.member_id, "member.create", "member", ident, key)
        return {"id": str(ident)}

    return UUID(receipt(c, p, "createMember", key, payload, perform)["id"])


def disable_member(c, p, key, member, expected):
    org_action(c, p, "member.manage")
    t = metadata.tables["members"]
    if not c.execute(select(t.c.id).where(t.c.org_id == p.org_id, t.c.id == member)).scalar():
        raise Denied("NOT_FOUND")

    def perform():
        now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
        compare_and_swap(c, "members", p.org_id, member, expected, {"disabled_at": now})
        audit(c, p.org_id, p.member_id, "member.disable", "member", member, key)
        return {"id": str(member)}

    return receipt(
        c, p, "disableMember", key, {"member": str(member), "expected": expected}, perform
    )


def _covers(g, scope, target):
    if g["scope_kind"] == "org":
        return True
    if g["scope_kind"] != scope:
        return False
    slot = {"business": "business_code"}.get(scope, scope + "_id")
    return str(g[slot]) == str(target)


def delegate(c, p, key, member, role, scope, target=None):
    grants = active_grants(c, p)
    if scope not in [
        "org",
        "business",
        "source",
        "raw_asset",
        "work",
        "knowledge",
        "standard",
        "file",
        "task",
    ] or (scope == "org") != (target is None):
        raise Denied("VALIDATION_FAILED")
    if not any(g["action_code"] == "grant.manage" and _covers(g, scope, target) for g in grants):
        raise Denied("ACCESS_DENIED")
    for name, ident in [("members", member), ("role_definitions", role)]:
        t = metadata.tables[name]
        if not c.execute(select(t.c.id).where(t.c.org_id == p.org_id, t.c.id == ident)).scalar():
            raise Denied("NOT_FOUND")
    # grant.manage explicitly delegates existing role packages within its scope;
    # role package changes themselves require org-scoped role.manage.
    slot = "business_code" if scope == "business" else scope + "_id"
    if slot not in SCOPE_SLOTS and scope != "org":
        raise Denied("VALIDATION_FAILED")

    def perform():
        ident = uuid4()
        c.execute(
            metadata.tables["grants"]
            .insert()
            .values(
                id=ident,
                org_id=p.org_id,
                member_id=member,
                role_id=role,
                scope_kind=scope,
                granted_by=p.member_id,
                **({slot: target} if scope != "org" else {}),
            )
        )
        audit(c, p.org_id, p.member_id, "grant.create", "grant", ident, key)
        return {"id": str(ident)}

    return UUID(
        receipt(
            c,
            p,
            "delegateGrant",
            key,
            {"member": str(member), "role": str(role), "scope": scope, "target": str(target)},
            perform,
        )["id"]
    )


def revoke(c, p, key, grant_id):
    grants = active_grants(c, p)
    t = metadata.tables["grants"]
    row = (
        c.execute(select(t).where(t.c.org_id == p.org_id, t.c.id == grant_id))
        .mappings()
        .one_or_none()
    )
    if not row:
        raise Denied("NOT_FOUND")
    target = (
        row.get("business_code")
        if row["scope_kind"] == "business"
        else row.get(row["scope_kind"] + "_id")
    )
    if not any(
        g["action_code"] == "grant.manage" and _covers(g, row["scope_kind"], target) for g in grants
    ):
        raise Denied("ACCESS_DENIED")

    def perform():
        if row["revoked_at"] is None:
            now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
            compare_and_swap(
                c, "grants", p.org_id, grant_id, row["lock_version"], {"revoked_at": now}
            )
        audit(c, p.org_id, p.member_id, "grant.revoke", "grant", grant_id, key)
        return {"id": str(grant_id)}

    return receipt(c, p, "revokeGrant", key, {"id": str(grant_id)}, perform)


def set_role_actions(c, p, key, role, actions):
    from app.core.models import ACTIONS

    org_action(c, p, "role.manage")
    if not actions or len(set(actions)) != len(actions) or not set(actions) <= set(ACTIONS.split()):
        raise Denied("VALIDATION_FAILED")
    r = metadata.tables["role_definitions"]
    if not c.execute(select(r.c.id).where(r.c.org_id == p.org_id, r.c.id == role)).scalar():
        raise Denied("NOT_FOUND")

    def perform():
        a = metadata.tables["role_actions"]
        c.execute(a.delete().where(a.c.org_id == p.org_id, a.c.role_id == role))
        for action in sorted(actions):
            c.execute(a.insert().values(org_id=p.org_id, role_id=role, action_code=action))
        audit(c, p.org_id, p.member_id, "role.actions_changed", "role", role, key)
        return {"id": str(role)}

    return receipt(
        c, p, "setRoleActions", key, {"role": str(role), "actions": sorted(actions)}, perform
    )


def read_audit(c, p, limit=100):
    org_action(c, p, "audit.read")
    if not 1 <= limit <= 100:
        raise Denied("VALIDATION_FAILED")
    t = metadata.tables["audit_events"]
    return [
        dict(row)
        for row in c.execute(
            select(t)
            .where(t.c.org_id == p.org_id)
            .order_by(t.c.occurred_at.desc(), t.c.id.desc())
            .limit(limit)
        ).mappings()
    ]


def catalog(c, p, kind):
    if kind == "roles":
        org_action(c, p, "role.manage")
        t = metadata.tables["role_definitions"]
        fields = [t.c.id, t.c.code, t.c.name, t.c.lock_version]
    elif kind == "members":
        org_action(c, p, "member.manage")
        t = metadata.tables["members"]
        fields = [t.c.id, t.c.login_name, t.c.display_name, t.c.disabled_at, t.c.lock_version]
    else:
        raise Denied("VALIDATION_FAILED")
    return [
        dict(row)
        for row in c.execute(
            select(*fields).where(t.c.org_id == p.org_id).order_by(t.c.id).limit(100)
        ).mappings()
    ]
