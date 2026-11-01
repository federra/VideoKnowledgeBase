"""Owner-only, insert-only transfer between existing PostgreSQL snapshot databases.

Run on the deployment host as postgres. No credentials or payloads are logged.
A source database is a restored, immutable local collection snapshot. --execute
is deliberately separate from the default comparison. Existing target rows are
never updated or deleted. Runtime and historical constraints are checked before
commit; a conflicting new unique identity or missing FK rolls back the batch.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import psycopg
from psycopg import sql

TABLES = (
    "provider_connections",
    "sources",
    "external_accounts",
    "external_account_aliases",
    "external_contents",
    "http_receipts",
    "tasks",
    "task_attempts",
    "collection_jobs",
    "collection_calls",
    "raw_assets",
    "task_inputs",
    "task_outputs",
    "account_observations",
    "content_observations",
    "intelligence_snapshots",
    "snapshot_entries",
    "comment_evidence",
    "audit_events",
)
ACTIVE = (
    "SELECT count(*) FROM tasks WHERE state IN ('queued','running','cancel_requested')"
)


def schema(c):
    rows = c.execute("""SELECT t.relname,array_agg(a.attname ORDER BY u.n)
       FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
       JOIN pg_namespace ns ON ns.oid=t.relnamespace
       CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY u(k,n)
       JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=u.k
       WHERE i.indisprimary AND ns.nspname='public' GROUP BY t.relname""").fetchall()
    return dict(rows)


def row_map(c, table, pk):
    query = sql.SQL(
        "SELECT jsonb_build_array({})::text,encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') FROM {} t"
    ).format(sql.SQL(",").join(sql.Identifier(x) for x in pk), sql.Identifier(table))
    return dict(c.execute(query).fetchall())


def fingerprint(c, definitions):
    return {name: row_map(c, name, keys) for name, keys in sorted(definitions.items())}


def compare(before, source):
    return {
        "missing": [key for key in source if key not in before],
        "existing_equal": sum(
            before.get(key) == value for key, value in source.items()
        ),
        "existing_different_preserved": sum(
            key in before and before[key] != value for key, value in source.items()
        ),
        "target_only_preserved": sum(key not in source for key in before),
    }


def unchanged(before, after):
    for name, rows in before.items():
        if any(after.get(name, {}).get(key) != digest for key, digest in rows.items()):
            raise RuntimeError("Existing target row changed: " + name)


def foreign_keys(c):
    constraints = c.execute("""SELECT n.nspname,t.relname,pn.nspname,p.relname,
         ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(i,n)
           JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=u.i ORDER BY u.n),
         ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY u(i,n)
           JOIN pg_attribute a ON a.attrelid=p.oid AND a.attnum=u.i ORDER BY u.n),
         k.conname,k.confmatchtype
         FROM pg_constraint k JOIN pg_class t ON t.oid=k.conrelid
         JOIN pg_namespace n ON n.oid=t.relnamespace
         JOIN pg_class p ON p.oid=k.confrelid JOIN pg_namespace pn ON pn.oid=p.relnamespace
         WHERE k.contype='f' AND n.nspname='public'""").fetchall()
    for ns, table, pns, parent, columns, parents, name, match in constraints:
        if match != "s":
            raise RuntimeError("Unsupported FK match mode: " + name)
        required = sql.SQL(" AND ").join(
            sql.SQL("c.{} IS NOT NULL").format(sql.Identifier(x)) for x in columns
        )
        links = sql.SQL(" AND ").join(
            sql.SQL("c.{}=p.{}").format(sql.Identifier(x), sql.Identifier(y))
            for x, y in zip(columns, parents, strict=True)
        )
        query = sql.SQL(
            "SELECT EXISTS(SELECT 1 FROM {}.{} c WHERE {} AND NOT EXISTS(SELECT 1 FROM {}.{} p WHERE {}))"
        ).format(
            sql.Identifier(ns),
            sql.Identifier(table),
            required,
            sql.Identifier(pns),
            sql.Identifier(parent),
            links,
        )
        if c.execute(query).fetchone()[0]:
            raise RuntimeError("Foreign key closure failed: " + name)
    return len(constraints)


def final_business_validation(c):
    # This is the same existing-tenant check used by the schema migrations.
    c.execute(
        "CREATE TEMP TABLE cip_migration_check(org_id uuid NOT NULL) ON COMMIT DROP"
    )
    for name, function in [
        ("sync_integrity", "cip_validate"),
        ("sync_relationships", "cip_relationships"),
    ]:
        c.execute(
            sql.SQL(
                "CREATE CONSTRAINT TRIGGER {} AFTER INSERT ON cip_migration_check DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(sql.Identifier(name), sql.Identifier(function))
        )
    c.execute("INSERT INTO cip_migration_check SELECT id FROM organizations")
    c.execute("SET CONSTRAINTS ALL IMMEDIATE")


ALLOWED_TASKS = {
    "intelligence.refresh",
    "intelligence.refresh.resume",
    "creator.resolve",
    "collect.hongguo",
    "collect.hongguo.saved",
    "collect.novels",
    "collect.tikhub-series",
    "series.normalize",
    "collect.creator-series",
    "collect.creator-posts",
    "collect.creator-posts.resume",
    "collect.microfilm",
    "collect.microfilm.resume",
    "creator.browser.comments",
    "creator.browser.reparse",
    "creator.series.reparse",
    "collect.redfox",
    "collect.tikhub-comments",
}
MUTABLE_INDEXES = {
    "sources",
    "external_accounts",
    "external_account_aliases",
    "external_contents",
    "provider_connections",
}


def scope_gate(source, definitions, before, source_rows, differences):
    # Auth/config/model/file changes are intentionally outside this operation.
    for table in ("raw_asset_events", "file_objects"):
        rows = row_map(source, table, definitions[table])
        delta = compare(before[table], rows)
        if delta["missing"] or delta["existing_different_preserved"]:
            raise RuntimeError("Unsupported dependency delta: " + table)
    for name, delta in differences.items():
        if name not in MUTABLE_INDEXES and delta["existing_different_preserved"]:
            raise RuntimeError("Immutable historical identity differs: " + name)

    def identities(table):
        position = definitions[table].index("id")
        return [json.loads(key)[position] for key in differences[table]["missing"]]

    tasks = identities("tasks")
    rows = source.execute(
        "SELECT kind FROM tasks WHERE id=ANY(%s::uuid[])", (tasks,)
    ).fetchall()
    if any(kind not in ALLOWED_TASKS for (kind,) in rows):
        raise RuntimeError("Non-collection task in append delta")
    providers = identities("provider_connections")
    rows = source.execute(
        "SELECT provider_code FROM provider_connections WHERE id=ANY(%s::uuid[])",
        (providers,),
    ).fetchall()
    if any(
        code
        not in {
            "novel_public",
            "hongguo_public",
            "douyin_public",
            "douyin_session",
            "tikhub",
            "redfox",
        }
        for (code,) in rows
    ):
        raise RuntimeError("Non-collection provider in append delta")
    raws = identities("raw_assets")
    orphan = source.execute(
        """SELECT EXISTS(SELECT 1 FROM raw_assets r WHERE r.id=ANY(%s::uuid[]) AND NOT (
       EXISTS(SELECT 1 FROM tasks t WHERE t.kind=ANY(%s::text[]) AND (t.id=r.processing_task_id OR t.raw_asset_id=r.id))
       OR EXISTS(SELECT 1 FROM collection_jobs j JOIN tasks t ON t.id=j.task_id WHERE j.id=r.collection_job_id AND t.kind=ANY(%s::text[]))
       OR EXISTS(SELECT 1 FROM task_inputs i JOIN tasks t ON t.id=i.task_id WHERE i.raw_asset_id=r.id AND t.kind=ANY(%s::text[]))
       OR EXISTS(SELECT 1 FROM task_outputs o JOIN tasks t ON t.id=o.task_id WHERE o.raw_asset_id=r.id AND t.kind=ANY(%s::text[]))
       ))""",
        (
            raws,
            sorted(ALLOWED_TASKS),
            sorted(ALLOWED_TASKS),
            sorted(ALLOWED_TASKS),
            sorted(ALLOWED_TASKS),
        ),
    ).fetchone()[0]
    if orphan:
        raise RuntimeError("Raw evidence is outside collection dependency closure")
    for table, parent_column in (
        ("task_attempts", "task_id"),
        ("task_inputs", "task_id"),
        ("task_outputs", "task_id"),
        ("collection_jobs", "task_id"),
    ):
        # These tables have either an id or composite PK; inspect the complete new rows.
        key_expr = sql.SQL("jsonb_build_array({})::text").format(
            sql.SQL(",").join(
                sql.SQL("x.{}").format(sql.Identifier(x)) for x in definitions[table]
            )
        )
        query = sql.SQL(
            "SELECT EXISTS(SELECT 1 FROM {} x JOIN tasks t ON t.id=x.{} WHERE {}=ANY(%s::text[]) AND NOT(t.kind=ANY(%s::text[])))"
        ).format(sql.Identifier(table), sql.Identifier(parent_column), key_expr)
        if source.execute(
            query, (differences[table]["missing"], sorted(ALLOWED_TASKS))
        ).fetchone()[0]:
            raise RuntimeError("Non-collection dependent rows: " + table)
    return {
        "raw_asset_event_delta": 0,
        "file_object_delta": 0,
        "new_collection_tasks": len(tasks),
        "new_raws_scope_verified": len(raws),
        "immutable_conflicts": 0,
    }


def run(source_db, target_db, *, port=55432, execute=False):
    if source_db == target_db or not re.fullmatch(r"cip_stage_[a-z0-9_]+", source_db):
        raise ValueError("Only an independent restored staging source is supported")
    if target_db != "cip_video_knowledge" and not re.fullmatch(
        r"cip_sync_test_[a-z0-9_]+", target_db
    ):
        raise ValueError("Unsupported target database")
    params = {"host": "/var/run/postgresql", "port": port, "user": "postgres"}
    with (
        psycopg.connect(dbname=source_db, **params) as source,
        psycopg.connect(dbname=target_db, **params) as target,
    ):
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        target.execute("SET LOCAL statement_timeout='1800s'")
        target.execute("SET LOCAL lock_timeout='10s'")
        source.execute("SET LOCAL timezone='UTC'")
        target.execute("SET LOCAL timezone='UTC'")
        for connection in (source, target):
            if (
                connection.execute(ACTIVE).fetchone()[0]
                or connection.execute(
                    "SELECT count(*) FROM sources WHERE enabled"
                ).fetchone()[0]
            ):
                raise RuntimeError("Only quiescent collection state may be transferred")
        if (
            source.execute("SELECT version_num FROM alembic_version").fetchone()
            != target.execute("SELECT version_num FROM alembic_version").fetchone()
        ):
            raise RuntimeError("Schema revisions differ")
        if (
            source.execute("SELECT id FROM organizations ORDER BY id").fetchall()
            != target.execute("SELECT id FROM organizations ORDER BY id").fetchall()
        ):
            raise RuntimeError("Organization boundaries differ")
        definitions = schema(target)
        if definitions != schema(source) or not set(TABLES).issubset(definitions):
            raise RuntimeError("Schema or primary keys differ")
        if execute:
            # The caller stops only this project's API/worker/Beat. These locks also
            # reject a forgotten writer, and protect the before/after proof.
            target.execute(
                sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
                    sql.SQL(",").join(
                        sql.Identifier(name) for name in sorted(definitions)
                    )
                )
            )
        before = fingerprint(target, definitions)
        source_rows = {
            name: row_map(source, name, definitions[name]) for name in TABLES
        }
        differences = {
            name: compare(before[name], source_rows[name]) for name in TABLES
        }
        excluded = {}
        for name, query, params in (
            (
                "http_receipts",
                "SELECT jsonb_build_array(org_id,member_id,operation,key)::text FROM http_receipts WHERE operation=ANY(%s::text[])",
                (
                    [
                        "refreshIntelligence",
                        "collectNovels",
                        "captureSeries",
                        "startCollection",
                    ],
                ),
            ),
            (
                "audit_events",
                """SELECT jsonb_build_array(a.id)::text FROM audit_events a WHERE
                (a.target_kind='task' AND EXISTS(SELECT 1 FROM tasks t WHERE t.id=a.target_id AND t.kind=ANY(%s::text[])))
                OR (a.target_kind IN ('source','provider_connection','collection_plan') AND a.action_code ~ '^(novel[.]|source[.]|collection[.]|connection[.])')
                OR (a.target_kind IN ('raw_asset','raw_assets') AND a.action_code ~ '^(hongguo[.]|creator[.]|comments[.]|series[.]|novel[.]|collection[.])')
                """,
                (sorted(ALLOWED_TASKS),),
            ),
        ):
            allowed = {row[0] for row in source.execute(query, params)}
            original = differences[name]["missing"]
            differences[name]["missing"] = [key for key in original if key in allowed]
            excluded[name] = len(original) - len(differences[name]["missing"])
        scope = scope_gate(source, definitions, before, source_rows, differences)
        report = {
            "scope_gate": scope,
            "excluded_unrelated_records": excluded,
            "source_database": source_db,
            "target_database": target_db,
            "execute": execute,
            "differences": {
                name: {k: len(v) if k == "missing" else v for k, v in value.items()}
                for name, value in differences.items()
            },
            "existing_rows_before": sum(map(len, before.values())),
        }
        if not execute:
            target.rollback()
            return report
        # Replay sealed historical records, not live executions. This setting is
        # local to this transaction; it is reset before any validation/commit.
        target.execute("SET LOCAL session_replication_role='replica'")
        inserted = {}
        for name in TABLES:
            missing = set(differences[name]["missing"])
            if not missing:
                inserted[name] = 0
                continue
            keys = definitions[name]
            query = sql.SQL(
                "SELECT jsonb_build_array({})::text,to_jsonb(t)::text FROM {} t"
            ).format(
                sql.SQL(",").join(sql.Identifier(x) for x in keys), sql.Identifier(name)
            )
            insert = sql.SQL(
                "INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{},%s::jsonb) ON CONFLICT DO NOTHING"
            ).format(sql.Identifier(name), sql.Identifier(name))
            n = 0
            with source.cursor(name="sync_" + name) as stream:
                stream.execute(query)
                for key, body in stream:
                    if key not in missing:
                        continue
                    if target.execute(insert, (body,)).rowcount != 1:
                        raise RuntimeError(
                            "New identity conflicts with preserved target: " + name
                        )
                    n += 1
            if n != len(missing):
                raise RuntimeError("Snapshot changed during transfer")
            inserted[name] = n
            print(
                json.dumps({"stage": "inserted", "table": name, "new_rows": n}),
                flush=True,
            )
        target.execute("SET LOCAL session_replication_role='origin'")
        report["foreign_keys_checked"] = foreign_keys(target)
        final_business_validation(target)
        after = fingerprint(target, definitions)
        unchanged(before, after)
        for name in TABLES:
            for key in differences[name]["missing"]:
                if after[name].get(key) != source_rows[name][key]:
                    raise RuntimeError("New row differs from source: " + name)
        report.update(
            inserted=inserted,
            existing_rows_unchanged=True,
            existing_rows_checked=sum(map(len, before.values())),
            pending_after=target.execute(ACTIVE).fetchone()[0],
            replication_mode=target.execute("SHOW session_replication_role").fetchone()[
                0
            ],
        )
        if report["pending_after"] or report["replication_mode"] != "origin":
            raise RuntimeError("Unexpected final execution state")
        target.commit()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source_db, args.target_db, port=args.port, execute=args.execute)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    args.report.chmod(0o600)
    print(
        json.dumps(
            {
                "completed": True,
                "executed": args.execute,
                "new_rows": sum(result.get("inserted", {}).values()),
                "existing_rows_unchanged": result.get("existing_rows_unchanged"),
            }
        )
    )


if __name__ == "__main__":
    main()
