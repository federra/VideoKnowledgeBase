"""Disposable browser acceptance API; no project rows, worker, or provider key.

Fixed credentials are test-only and valid only while this temporary process runs.
"""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from alembic import command
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from scripts.database import config, local_url, render

from app.collection.console import create_source, patch_source
from app.collection.handler import Collect
from app.collection.service import submit
from app.connectors.redfox import RedFox
from app.contracts.models import CollectionCreate, ConsoleSourceCreate, SourcePatch
from app.core.database import build_engine
from app.core.database_roles import grant_application
from app.core.models import metadata
from app.security.governance import bootstrap
from app.security.sessions import MemberPrincipal
from app.tasks.service import cancel


def main():
    url = local_url()
    suffix = uuid4().hex
    name, role = "cip_s062_browser_" + suffix, "cip_s062_role_" + suffix
    admin = build_engine(url.set(database="postgres"))
    owner = None
    proc = None
    created = False
    role_created = False
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql(f"CREATE DATABASE {name}")
        created = True
        test_url = url.set(database=name)
        command.upgrade(config(render(test_url)), "head")
        owner = build_engine(test_url)
        db_password = secrets.token_urlsafe(32)
        with owner.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.Literal(db_password))
            )
            grant_application(cursor, role)
        role_created = True
        with owner.begin() as c:
            org, member = bootstrap(
                c, "隔离浏览器验收（非项目数据）", "preview", "ConsolePreviewOnly-LongPassword2026!"
            )
            for code in ("O", "E"):
                oid = c.exec_driver_sql(
                    "SELECT id FROM role_definitions WHERE org_id=%s AND code=%s", (org, code)
                ).scalar_one()
                c.execute(
                    metadata.tables["grants"]
                    .insert()
                    .values(
                        id=uuid4(),
                        org_id=org,
                        member_id=member,
                        role_id=oid,
                        scope_kind="org",
                        granted_by=member,
                    )
                )
            p = MemberPrincipal(org, member)
            source = create_source(
                c,
                p,
                ConsoleSourceCreate(
                    name="隔离验收来源", address="漫剧", business_code="motion_comic"
                ),
                str(uuid4()),
            )
            source = patch_source(
                c,
                p,
                source["id"],
                SourcePatch(expected_lock_version=source["lock_version"], enabled=True),
                str(uuid4()),
            )
            job = submit(
                c,
                p,
                CollectionCreate(
                    source_id=source["id"],
                    provider_connection_id=source["plan"]["connection_id"],
                    capability_code="douyin.account.search",
                ),
                str(uuid4()),
                Collect(RedFox(lambda: None)),
            )
            from uuid import UUID

            cancel(c, p, UUID(job["task"]["task_id"]), int(job["task"]["lock_version"]))
            patch_source(
                c,
                p,
                source["id"],
                SourcePatch(expected_lock_version=source["lock_version"], enabled=False),
                str(uuid4()),
            )
        print("Preview organization: " + str(org), flush=True)
        print(
            "Disposable preview only; provider key empty; no worker. Ctrl-C cleans database and role.",
            flush=True,
        )
        env = {
            **os.environ,
            "APPLICATION_DATABASE_URL": render(test_url.set(username=role, password=db_password)),
            "REDFOX_API_KEY": "",
            "LOCAL_SINGLE_USER": "false",
            "ALLOWED_ORIGINS": json.dumps(["http://127.0.0.1:5180", "http://localhost:5180"]),
        }
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8010",
            ],
            cwd=ROOT / "backend",
            env=env,
        )
        proc.wait(timeout=1800)
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if owner is not None:
            if role_created:
                with owner.begin() as c:
                    cursor = c.connection.driver_connection.cursor()
                    cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            owner.dispose()
        if created:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
                c.exec_driver_sql(f"DROP DATABASE {name} WITH (FORCE)")
        admin.dispose()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001 - only safe exception class reaches logs
        print("Preview failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
