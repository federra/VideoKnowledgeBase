"""All callers use one explicit transaction; no commits hidden inside mutations."""

from uuid import uuid4

from sqlalchemy import select

from app.core.models import metadata
from app.security.errors import Denied
from app.security.primitives import digest


def lock_org(c, org):
    c.exec_driver_sql(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("cip:b1:" + str(org),)
    )


def audit(c, org, actor, action, kind, target=None, request_id=None):
    c.execute(
        metadata.tables["audit_events"]
        .insert()
        .values(
            id=uuid4(),
            org_id=org,
            actor_member_id=actor,
            action_code=action,
            target_kind=kind,
            target_id=target,
            request_id=str(request_id or uuid4()),
            safe_details={},
        )
    )


def receipt(c, p, operation, key, payload, perform):
    # Caller MUST authenticate and authorize before entering, including replay.
    lock_org(c, p.org_id)
    t = metadata.tables["http_receipts"]
    scope = (
        t.c.org_id == p.org_id,
        t.c.member_id == p.member_id,
        t.c.operation == operation,
        t.c.key == key,
    )
    row = c.execute(select(t).where(*scope)).mappings().one_or_none()
    sha = digest(payload)
    if row:
        if row["input_sha256"] != sha:
            raise Denied("IDEMPOTENCY_CONFLICT")
        return row["response"]
    response = perform()
    c.execute(
        t.insert().values(
            org_id=p.org_id,
            member_id=p.member_id,
            operation=operation,
            key=key,
            input_sha256=sha,
            response=response,
        )
    )
    return response
