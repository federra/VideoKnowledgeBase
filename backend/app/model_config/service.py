"""Console-only mutable heads over existing immutable AI config revisions."""

from uuid import UUID

from sqlalchemy import func, select, update

from app.collection.service import get, insert
from app.core.models import metadata
from app.model_config.contracts import STAGES
from app.model_config.transport import credential_ready
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, receipt


def authorize(c, p, business=None, *, edit=True):
    refresh(c, p)
    if not Authorizer(c, p).allowed(
        "model.configure" if edit else "content.write",
        {("org", str(p.org_id))} | ({("business", business)} if business else set()),
    ):
        raise Denied("ACCESS_DENIED")


def sources(c, org):
    t = metadata.tables["model_sources"]
    return (
        c.execute(select(t).where(t.c.org_id == org).order_by(t.c.created_at, t.c.id))
        .mappings()
        .all()
    )


def source_view(c, org, row):
    rev = get(c, "ai_config_revisions", org, row["config_revision_id"])
    params = rev["parameters"]
    return {
        **params,
        "id": str(row["id"]),
        "enabled": row["enabled"],
        "version": rev["version_no"],
        "lock_version": str(row["lock_version"]),
        "credential_ready": credential_ready(params["secret_ref"]),
    }


def binding(c, org, business):
    t = metadata.tables["model_bindings"]
    return (
        c.execute(select(t).where(t.c.org_id == org, t.c.business_code == business))
        .mappings()
        .one_or_none()
    )


def view(c, p, business):
    authorize(c, p)
    current = binding(c, p.org_id, business)
    return {
        "sources": [source_view(c, p.org_id, x) for x in sources(c, p.org_id)],
        "bindings": current["bindings"] if current else {},
        "lock_version": str(current["lock_version"]) if current else "0",
    }


def save_source(c, p, body, key):
    authorize(c, p)

    def perform():
        old = get(c, "model_sources", p.org_id, body.id) if body.id else None
        if body.id and not old:
            raise Denied("NOT_FOUND")
        if old and str(old["lock_version"]) != body.expected_lock_version:
            raise Denied("VERSION_CONFLICT")
        if old and old["capability"] != body.capability:
            bt = metadata.tables["model_bindings"]
            bindings = c.execute(select(bt.c.bindings).where(bt.c.org_id == p.org_id)).scalars()
            if any(str(body.id) in values.values() for values in bindings):
                raise Denied("VALIDATION_FAILED")
        if any(
            x["name"].casefold() == body.name.casefold() and x["id"] != body.id
            for x in sources(c, p.org_id)
        ):
            raise Denied("VALIDATION_FAILED")
        values = body.model_dump(mode="json", exclude={"id", "expected_lock_version", "enabled"})
        # New connection per revision preserves previous credential references and enables.
        from uuid import uuid4

        ident = body.id or uuid4()
        number = (
            get(c, "ai_config_revisions", p.org_id, old["config_revision_id"])["version_no"] + 1
            if old
            else 1
        )
        connection = insert(
            c,
            "provider_connections",
            p.org_id,
            provider_code=body.provider,
            name=f"model:{ident}:v{number}",
            secret_ref=body.secret_ref,
            enabled=body.enabled,
        )
        revision = insert(
            c,
            "ai_config_revisions",
            p.org_id,
            config_key=f"model:{ident}",
            version_no=number,
            task_kind="topics.generate",
            provider_connection_id=connection,
            model_identifier=body.model,
            parameters=values,
            output_schema={},
            content_sha256=digest(values),
            created_by=p.member_id,
        )
        t = metadata.tables["model_sources"]
        patch = {
            "name": body.name,
            "capability": body.capability,
            "connection_id": connection,
            "config_revision_id": revision,
            "enabled": body.enabled,
        }
        if old:
            c.execute(
                update(t)
                .where(t.c.org_id == p.org_id, t.c.id == ident)
                .values(
                    **patch, lock_version=t.c.lock_version + 1, updated_at=func.clock_timestamp()
                )
            )
        else:
            insert(c, "model_sources", p.org_id, id=ident, **patch)
        audit(c, p.org_id, p.member_id, "model.config.saved", "model_source", ident)
        return source_view(c, p.org_id, get(c, "model_sources", p.org_id, ident))

    result = receipt(c, p, "saveModelSource", key, body.model_dump(mode="json"), perform)
    # Replays expose current readiness only, no credentials.
    return {**result, "credential_ready": credential_ready(result["secret_ref"])}


def save_bindings(c, p, body, key):
    authorize(c, p)

    def perform():
        old = binding(c, p.org_id, body.business_code)
        if body.expected_lock_version != (str(old["lock_version"]) if old else "0"):
            raise Denied("VERSION_CONFLICT")
        for stage, source in body.bindings.items():
            row = get(c, "model_sources", p.org_id, source)
            if not row or not row["enabled"] or row["capability"] != STAGES[stage]:
                raise Denied("VALIDATION_FAILED")
        t = metadata.tables["model_bindings"]
        values = {k: str(v) for k, v in body.bindings.items()}
        if old:
            c.execute(
                update(t)
                .where(t.c.org_id == p.org_id, t.c.id == old["id"])
                .values(
                    bindings=values,
                    lock_version=t.c.lock_version + 1,
                    updated_at=func.clock_timestamp(),
                )
            )
        else:
            insert(c, "model_bindings", p.org_id, business_code=body.business_code, bindings=values)
        audit(c, p.org_id, p.member_id, "model.bindings.saved", "business")
        return view(c, p, body.business_code)

    return receipt(c, p, "saveModelBindings", key, body.model_dump(mode="json"), perform)


def resolve(c, p, business, stage):
    """Resolve a saved current binding, checking content.write rather than admin permission."""
    authorize(c, p, business, edit=False)
    head = binding(c, p.org_id, business)
    source_id = head["bindings"].get(stage) if head else None
    row = get(c, "model_sources", p.org_id, UUID(source_id)) if source_id else None
    if not row or not row["enabled"] or row["capability"] != STAGES.get(stage):
        raise Denied("MODEL_NOT_CONFIGURED")
    rev = get(c, "ai_config_revisions", p.org_id, row["config_revision_id"])
    conn = get(c, "provider_connections", p.org_id, row["connection_id"])
    values = rev["parameters"]
    if (
        not conn
        or not conn["enabled"]
        or conn["secret_ref"] != values["secret_ref"]
        or conn["provider_code"] != values["provider"]
        or values["provider"] not in ("deepseek", "openai")
        or row["capability"] != "text"
        or not credential_ready(values["secret_ref"])
    ):
        raise Denied("MODEL_NOT_CONFIGURED")
    return {
        **values,
        "revision_id": rev["id"],
        "source_id": row["id"],
        "connection_id": conn["id"],
        "source_lock_version": str(row["lock_version"]),
        "binding_lock_version": str(head["lock_version"]),
    }
