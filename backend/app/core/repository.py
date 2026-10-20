"""Small transaction primitives. S05 adds authenticated action checks around these."""

from uuid import uuid4

from sqlalchemy import select, update

from app.core.models import metadata


class VersionConflict(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


def compare_and_swap(connection, table_name, organization, identity, expected, values):
    connection.exec_driver_sql(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("cip:b1:" + str(organization),)
    )
    table = metadata.tables[table_name]
    if set(values) & {"id", "org_id", "lock_version", "updated_at"}:
        raise ValueError("Identity and concurrency fields are managed by the repository.")
    row = connection.execute(
        update(table)
        .where(
            table.c.org_id == organization,
            table.c.id == identity,
            table.c.lock_version == expected,
        )
        .values(**values, lock_version=expected + 1)
        .returning(table.c.id)
    ).scalar_one_or_none()
    if row is None:
        raise VersionConflict("VERSION_CONFLICT")
    return row


def create_task(connection, values, inputs=()):
    table = metadata.tables["tasks"]
    # One tenant mutex is shared with triggers: no read-then-insert idempotency race.
    connection.exec_driver_sql(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("cip:b1:" + str(values["org_id"]),)
    )
    row = (
        connection.execute(
            select(table).where(
                table.c.org_id == values["org_id"],
                table.c.kind == values["kind"],
                table.c.idempotency_key == values["idempotency_key"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is not None:
        if row["input_sha256"] != values["input_sha256"]:
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
        return row["id"], False
    identity = values.get("id", uuid4())
    connection.execute(table.insert().values(**{**values, "id": identity}))
    for position, item in enumerate(inputs):
        connection.execute(
            metadata.tables["task_inputs"]
            .insert()
            .values(**item, org_id=values["org_id"], task_id=identity, position=position)
        )
    connection.exec_driver_sql(
        "SELECT cip_seal('tasks',%s,%s,'inputs')", (values["org_id"], identity)
    )
    return identity, True


def claim_task(connection, organization, identity, expected_version, *, lease_seconds=60):
    if not 1 <= lease_seconds <= 3600:
        raise ValueError("Lease must be between 1 and 3600 seconds.")
    return tuple(
        connection.exec_driver_sql(
            "SELECT * FROM cip_claim_task(%s,%s,%s,%s)",
            (organization, identity, expected_version, lease_seconds),
        ).one()
    )


def finish_task(
    connection,
    organization,
    identity,
    attempt,
    token,
    expected_version,
    *,
    outcome="succeeded",
    business_outcome="completed",
    error=None,
):
    if outcome not in ("succeeded", "failed", "cancelled"):
        raise ValueError("Invalid task outcome.")
    connection.exec_driver_sql(
        "SELECT cip_finish_task(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            organization,
            identity,
            attempt,
            token,
            expected_version,
            outcome,
            business_outcome if outcome == "succeeded" else None,
            error,
        ),
    )
