"""Disposable S06.3 browser fixture: synthetic HTTP only, no project samples or worker."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from alembic import command
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from scripts.database import config, local_url, render

from app.collection.handler import Collect
from app.collection.service import configure_connection, configure_source, submit
from app.connectors.redfox import VERSION, RedFox
from app.contracts.models import CollectionCreate
from app.core.database import build_engine
from app.core.database_roles import grant_application
from app.core.repository import compare_and_swap
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def seed(engine):
    with engine.begin() as c:
        _, context = enter(c)
        p = MemberPrincipal(context["org_id"], context["member_id"])
        connection = configure_connection(c, p, "隔离合成响应，无外部调用")
    calls = []

    def transport(request):
        index = len(calls)
        calls.append(request)
        author = json.loads(request.content)["userId"]
        return httpx.Response(
            200,
            json={
                "code": 2000,
                "data": {
                    "list": [
                        {
                            "videoId": f"synthetic-{index}",
                            "authorUid": author,
                            "authorName": "隔离验收达人 " + author[-1],
                            "content": (
                                "隔离测试原始描述：不是项目真实内容。"
                                + ("长描述用于核验截断、悬停全文和键盘查看。" * 24)
                                if index == 0
                                else f"隔离验收作品 {index + 1}，用于检查分页与缺失值。"
                            ),
                            "likeCount": 0 if index == 0 else index * 10,
                            "opusUrl": None,
                        }
                    ]
                },
            },
        )

    handler = Collect(
        RedFox(lambda: "synthetic-only", transport=httpx.MockTransport(transport)),
        min_interval=0,
    )
    runner = Runner(engine, {("collect.redfox", VERSION): handler})
    for index in range(12):
        with engine.begin() as c:
            source = configure_source(
                c,
                p,
                f"隔离作品来源 {index + 1}",
                "account",
                f"synthetic-author-{index % 2}",
                enabled=True,
            )
            job = submit(
                c,
                p,
                CollectionCreate(
                    source_id=source,
                    provider_connection_id=connection,
                    capability_code="douyin.creator.works",
                ),
                str(uuid4()),
                handler,
            )
        assert runner.run(p.org_id, UUID(job["task"]["task_id"])) == "succeeded"
        with engine.begin() as c:
            version = c.exec_driver_sql(
                "SELECT lock_version FROM sources WHERE id=%s", (source,)
            ).scalar_one()
            compare_and_swap(
                c, "sources", p.org_id, source, version, {"enabled": False}
            )
    assert len(calls) == 12


def main():
    url = local_url()
    suffix = uuid4().hex
    name, role = "cip_s063_browser_" + suffix, "cip_s063_role_" + suffix
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
        seed(owner)
        password = secrets.token_urlsafe(32)
        with owner.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            grant_application(cursor, role)
        role_created = True
        env = {
            **os.environ,
            "APPLICATION_DATABASE_URL": render(
                test_url.set(username=role, password=password)
            ),
            "LOCAL_SINGLE_USER": "true",
            "REDFOX_API_KEY": "",
            "ALLOWED_ORIGINS": json.dumps(["http://127.0.0.1:5180", "http://localhost:5180"]),
        }
        print(
            "Disposable browser fixture: 12 synthetic works, no external requests; Ctrl-C cleans database and role.",
            flush=True,
        )
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
                    cursor.execute(
                        sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role))
                    )
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
    except Exception as exc:  # noqa: BLE001 - emit only the safe exception class
        print("Preview failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
