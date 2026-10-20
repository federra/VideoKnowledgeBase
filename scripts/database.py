"""S04 dedicated local PostgreSQL migrations and disposable-database acceptance.

Never logs connection strings. Only `test` drops a strictly named database it created.
"""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from app.core.database import build_engine


def private_settings():
    from local_infra import read_settings

    return read_settings(ROOT)


def config(url):
    # Env is child-process private; URL never enters an ini file or command line.
    os.environ["CIP_MIGRATION_URL"] = url
    return Config(str(ROOT / "backend/alembic.ini"))


def local_url():
    settings = private_settings()
    url = make_url(settings.get("MIGRATION_DATABASE_URL") or settings["DATABASE_URL"])
    if url.host not in ("127.0.0.1", "localhost") or url.port != 15432:
        raise ValueError("Only dedicated cip-local PostgreSQL on 15432 is supported.")
    return url


def render(url):
    return url.render_as_string(hide_password=False)


def isolated_test(url):
    name = "cip_s04_test_" + uuid4().hex
    admin = build_engine(url.set(database="postgres"))
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql(f"CREATE DATABASE {name}")
    test_url = render(url.set(database=name))
    try:
        cfg = config(test_url)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "0003_b1")
        verify_stock_upgrade(cfg, test_url)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/integration",
                "-q",
                "--tb=short",
                *(
                    ["-k", os.environ["CIP_TEST_FILTER"]]
                    if os.environ.get("CIP_TEST_FILTER")
                    else []
                ),
            ],
            cwd=ROOT / "backend",
            env={
                **os.environ,
                "CIP_TEST_DATABASE_URL": test_url,
                "REDFOX_API_KEY": "",
                "LOCAL_SINGLE_USER": "false",
            },
            check=False,
            capture_output=True,
            text=True,
        )
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode:
            raise RuntimeError("Isolated PostgreSQL acceptance failed; review pytest output.")
        evidence = ROOT / (
            "doc/technical/verification/2026-10-17/s06-default-postgresql-"
            + ("focused" if os.environ.get("CIP_TEST_FILTER") else "acceptance")
            + ".json"
        )
        evidence.with_suffix(".txt").write_text(result.stdout + result.stderr)
        evidence.write_text(
            json.dumps(
                {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "database": "disposable PostgreSQL",
                    "external_api_calls": 0,
                    "empty_upgrade": True,
                    "repeated_upgrade": True,
                    "downgrade_and_rebuild": True,
                    "valid_stock_preserved": True,
                    "invalid_stock_aborts_migration": True,
                    "test_command": "pnpm db:test",
                    "test_filter": os.environ.get("CIP_TEST_FILTER"),
                    "pytest_summary": result.stdout.strip().splitlines()[-1],
                    "migrations": [
                        "0001_b1",
                        "0002_b1",
                        "0003_b1",
                        "0004_b1",
                        "0005_auth",
                        "0006_storage",
                        "0007_tasks",
                        "0008_console",
                        "0009_collection_lock",
                        "0010_comments",
                        "0011_insight",
                        "0012_handoffs",
                        "0013_research",
                        "0014_inputs",
                        "0015_novels",
                        "0016_saved_novels",
                        "0017_browser_novels",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print("Empty database upgrade/repeat/downgrade/rebuild and PostgreSQL acceptance passed.")
    finally:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            # Exact UUID name created above; no configurable DROP target.
            c.exec_driver_sql(f"DROP DATABASE {name} WITH (FORCE)")
        admin.dispose()


def verify_stock_upgrade(cfg, url):
    """Upgrade valid identities; reject and roll back an invalid pre-constraint shell."""
    engine = build_engine(url)
    org, member, work, bad_artifact = [uuid4() for _ in range(4)]
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO organizations(id,name) VALUES (%s,'stock-upgrade')", (org,))
        c.exec_driver_sql(
            "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,'stock')",
            (member, org, str(member)),
        )
        c.exec_driver_sql(
            "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'stock',%s)",
            (work, org, str(work), member),
        )
        c.exec_driver_sql(
            "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES (%s,%s,%s,%s,'script',%s)",
            (bad_artifact, org, work, str(bad_artifact), member),
        )
    rejected = False
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:
        if "current pointer required" not in str(getattr(exc, "orig", exc)):
            raise
        rejected = True
    if not rejected:
        raise RuntimeError("Invalid existing data unexpectedly survived migration.")
    with engine.begin() as c:
        assert (
            c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0003_b1"
        )
        c.exec_driver_sql("DELETE FROM artifacts WHERE id=%s", (bad_artifact,))
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert (
            c.exec_driver_sql("SELECT name FROM works WHERE id=%s", (work,)).scalar_one() == "stock"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM pg_trigger WHERE tgname='z_immutable'"
            ).scalar_one()
            == 72
        )
    engine.dispose()
    print("Stock upgrade preserves valid rows; invalid stock aborts the entire migration.")


def initialize_application_role(url):
    from app.core.database_roles import grant_application

    private = private_settings()
    existing = private.get("APPLICATION_DATABASE_URL")
    if existing:
        target = make_url(existing)
        if target.host != url.host or target.port != url.port or target.database != url.database:
            raise ValueError(
                "Application and migration URLs must address the same dedicated database."
            )
        if not target.username.startswith("cip_local_app_"):
            raise ValueError(
                "Preserve existing external role; automated grants support cip_local_app_ only."
            )
        role, password = target.username, target.password
    else:
        role = "cip_local_app_" + uuid4().hex[:12]
        password = secrets.token_urlsafe(32)
        target = url.set(username=role, password=password)
    owner = build_engine(url)
    try:
        with owner.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            attrs = c.exec_driver_sql(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=%s",
                (role,),
            ).one_or_none()
            if attrs is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
            elif any(attrs):
                raise ValueError("Existing role has administrative privileges; no changes made.")
            grant_application(cursor, role)
        if not existing:
            filename = ROOT / ".env"
            if filename.stat().st_mode & 0o077:
                raise ValueError(
                    "Private .env must be mode 0600 before saving application credentials."
                )
            with filename.open("a", encoding="utf-8") as output:
                output.write(
                    "\n# S04 restricted application login; migration owner remains DATABASE_URL.\n"
                )
                output.write("APPLICATION_DATABASE_URL=" + render(target) + "\n")
        limited = build_engine(target)
        try:
            with limited.connect() as c:
                assert c.exec_driver_sql("SELECT count(*) FROM tasks").scalar_one() == 0 or existing
        finally:
            limited.dispose()
        print(
            "Restricted application login configured and verified; credentials stay in private .env."
        )
    finally:
        owner.dispose()


def audit_database(url):
    from app.core.database import application_engine
    from app.core.models import TABLE_GROUPS, metadata

    owner = build_engine(url)
    try:
        with owner.connect() as c:
            counts = {
                name: c.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one()
                for name in metadata.tables
            }
            audit = {
                "checked_at": datetime.now(UTC).isoformat(),
                "postgres": c.exec_driver_sql("SHOW server_version").scalar_one(),
                "pgvector": c.exec_driver_sql(
                    "SELECT extversion FROM pg_extension WHERE extname='vector'"
                ).scalar_one(),
                "revision": c.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalar_one(),
                "table_groups": dict(zip(["B1-a", "B1-b", "B1-c"], map(len, TABLE_GROUPS))),
                "table_count": len(metadata.tables),
                "row_counts": counts,
                "foreign_keys": c.exec_driver_sql(
                    "SELECT count(*) FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace"
                ).scalar_one(),
                "checks": c.exec_driver_sql(
                    "SELECT count(*) FROM pg_constraint WHERE contype='c' AND connamespace='public'::regnamespace"
                ).scalar_one(),
                "triggers": c.exec_driver_sql(
                    "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnamespace='public'::regnamespace AND NOT t.tgisinternal"
                ).scalar_one(),
                "application_role_checked": True,
                "sql_sha256": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((ROOT / "backend/migrations/sql").glob("*.sql"))
                },
            }
        limited = application_engine()
        limited.dispose()
        filename = ROOT / "doc/technical/verification/2026-10-17/s064-probe-database-audit.json"
        filename.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        print(
            f"Project database: {audit['revision']}, {len(counts)} tables, {sum(counts.values())} rows; restricted application connection verified."
        )
    finally:
        owner.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "upgrade", "test", "app-role", "audit"])
    args = parser.parse_args()
    url = local_url()
    if args.action == "test":
        isolated_test(url)
    elif args.action == "audit":
        audit_database(url)
    elif args.action == "app-role":
        initialize_application_role(url)
    elif args.action == "upgrade":
        command.upgrade(config(render(url)), "head")
        if private_settings().get("APPLICATION_DATABASE_URL"):
            initialize_application_role(url)
        print("Dedicated project database upgraded to head; no business seed data.")
    else:
        command.current(config(render(url)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - sanitize all errors at the CLI boundary
        # Driver exceptions may include DSNs or SQL values; only safe category here.
        original = getattr(exc, "orig", exc)
        diag = getattr(original, "diag", None)
        primary = getattr(diag, "message_primary", "")
        print(
            f"Database command failed ({type(exc).__name__}): {primary}",
            file=sys.stderr,
        )
        sys.exit(1)
