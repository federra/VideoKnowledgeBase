"""Least-privilege grants, executed only by the migration owner on a chosen database."""

from psycopg import sql

from app.core.models import metadata


def grant_application(cursor, role):
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(sql.Identifier(role))
    )
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {}").format(sql.Identifier(role))
    )
    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
    cursor.execute(
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(role))
    )
    for name, table in metadata.tables.items():
        if name in ("business_lines", "platforms"):
            continue
        if name == "task_attempts":
            continue
        cursor.execute(
            sql.SQL("GRANT INSERT ON {} TO {}").format(sql.Identifier(name), sql.Identifier(role))
        )
        if name in ("http_receipts", "file_intakes"):
            continue
        if name == "auth_sessions":
            columns = ["revoked_at"]
        elif name == "organizations":
            columns = ["name", "updated_at", "lock_version"]
        elif name == "tasks":
            columns = [
                "execution_authorized_by",
                "available_at",
                "inputs_sealed_at",
                "lock_version",
                "updated_at",
            ]
        else:
            columns = table.c.keys()
        cursor.execute(
            sql.SQL("GRANT UPDATE ({}) ON {} TO {}").format(
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.Identifier(name),
                sql.Identifier(role),
            )
        )
    # Association action removal is a supported authorization change, not history deletion.
    cursor.execute(sql.SQL("GRANT DELETE ON role_actions TO {}").format(sql.Identifier(role)))
    # Internal trigger routines cannot be invoked as ordinary SQL; application entry
    # functions are invoker rights and remain subject to table/column guards.
    cursor.execute("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC")
    for signature in [
        "vector_dims(vector)",
        "cip_seal(text,uuid,uuid,text)",
        "cip_claim_task(uuid,uuid,bigint,integer)",
        "cip_finish_task(uuid,uuid,uuid,uuid,bigint,text,text,text)",
        "cip_task_control(uuid,uuid,bigint,text,uuid,uuid,integer,text)",
        "cip_input_contains(uuid,uuid,uuid)",
        "cip_graph_edges(uuid)",
    ]:
        cursor.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(signature), sql.Identifier(role)
            )
        )
