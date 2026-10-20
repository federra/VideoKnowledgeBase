"""Run the actual TypeScript client against a disposable PostgreSQL/API/filesystem.

No project accounts/rows, no paid calls, no browser password storage or test-only routes.
"""

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from alembic import command
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from database import config, local_url, render

from app.core.database import build_engine
from app.core.database_roles import grant_application
from app.core.models import metadata
from app.security.governance import bootstrap
from app.security.primitives import hash_password
from tests.integration.test_security import grant


def main():
    owner_url = local_url()
    name, role = "cip_s055_test_" + uuid4().hex, "cip_s055_role_" + uuid4().hex
    admin = build_engine(owner_url.set(database="postgres"))
    owner, proc = None, None
    created, role_created = False, False
    evidence = ROOT / "doc/technical/verification/2026-10-17"
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql(f"CREATE DATABASE {name}")
        created = True
        url = owner_url.set(database=name)
        command.upgrade(config(render(url)), "head")
        owner = build_engine(url)
        password, db_password = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with owner.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.Literal(db_password))
            )
            role_created = True
            grant_application(cursor, role)
            org, writer = bootstrap(c, "disposable frontend acceptance", "writer", password)
            wid = uuid4()
            c.execute(
                metadata.tables["works"]
                .insert()
                .values(
                    id=wid,
                    org_id=org,
                    business_code="motion_comic",
                    work_number=str(wid),
                    name="test only",
                    created_by=writer,
                )
            )
            grant(
                c, org, writer, writer, ["content.read", "content.write", "file.read"], "work", wid
            )
            for login_name in ["viewer", "empty"]:
                member = uuid4()
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
                if login_name == "viewer":
                    grant(c, org, writer, member, ["content.read"], "work", wid)
        with tempfile.TemporaryDirectory(prefix="cip-s055-") as directory:
            private = Path(directory).resolve()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            env = {
                **os.environ,
                "APPLICATION_DATABASE_URL": render(url.set(username=role, password=db_password)),
                "STORAGE_ROOT": str(private / "data"),
                "EXTERNAL_MEDIA_HOSTS": "[]",
                "LOCAL_SINGLE_USER": "false",
                "REDFOX_API_KEY": "",
            }
            with (private / "api.log").open("w") as log:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                    ],
                    cwd=ROOT / "backend",
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                end = time.monotonic() + 15
                while time.monotonic() < end:
                    if proc.poll() is not None:
                        raise RuntimeError("Disposable API failed to start")
                    try:
                        if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Disposable API startup timeout")
                fixture = private / "fixture.json"
                fd = os.open(fixture, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(
                        {
                            "base_url": base,
                            "org": str(org),
                            "work": str(wid),
                            "password": password,
                            "evidence": str(evidence / "s055-real-http.json"),
                        },
                        f,
                    )
                result = subprocess.run(
                    ["pnpm", "exec", "vitest", "run", "--config", "vitest.wire.config.ts"],
                    cwd=ROOT / "frontend",
                    env={**os.environ, "CIP_FRONTEND_FIXTURE": str(fixture)},
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                output = result.stdout + result.stderr
                (evidence / "s055-real-http-tests.log").write_text(output)
                print(output, end="")
                if result.returncode:
                    raise RuntimeError("Frontend real HTTP acceptance failed")
            with owner.connect() as c:
                assert c.exec_driver_sql("SELECT count(*) FROM file_objects").scalar_one() == 1
                assert c.exec_driver_sql("SELECT count(*) FROM file_intakes").scalar_one() == 1
            print(
                "Actual TypeScript / HTTP / restricted PostgreSQL / filesystem acceptance passed."
            )
    finally:
        if proc is not None:
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
    except Exception as exc:  # noqa: BLE001 - no private URLs/passwords in exception output
        print("Frontend acceptance failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
