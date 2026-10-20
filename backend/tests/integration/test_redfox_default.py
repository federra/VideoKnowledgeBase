"""Default-order search to sealed board, isolated PostgreSQL and synthetic HTTP only."""

from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from tests.integration.test_collection import prepared
from tests.test_redfox_default import CAP, payload

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def exercise(engine, setup):
    from app.collection.handler import Collect
    from app.collection.service import configure_source, submit
    from app.connectors.redfox import VERSION, RedFox
    from app.contracts.models import CollectionCreate
    from app.intelligence.service import feed, shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    _, _, org, _, _, connection, *rest = prepared(engine, setup)
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=payload())

    handler = Collect(
        RedFox(lambda: "offline", transport=httpx.MockTransport(transport)), min_interval=0
    )
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        source = configure_source(c, p, "漫剧默认相关性", "keyword", "漫剧", enabled=True)
        accepted = submit(
            c,
            p,
            CollectionCreate(
                source_id=source,
                provider_connection_id=connection,
                capability_code=CAP,
                max_items=10,
            ),
            str(uuid4()),
            handler,
        )
    runner = Runner(engine, {("collect.redfox", VERSION): handler})
    tid = UUID(accepted["task"]["task_id"])
    assert runner.run(org, tid) == "succeeded"
    assert runner.run(org, tid) == "ignored" and len(calls) == 1
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        day = shanghai_date()
        result = feed(c, p, "motion_comic", day, "board")
        from app.contracts.models import IntelligenceFeed

        assert IntelligenceFeed.model_validate(result).keyword_ranking_status == "default_order"
        assert result["total"] == "10" and result["keyword_ranking_status"] == "default_order"
        assert [x["entry"]["observation"]["platform_id"] for x in result["items"]] == [
            str(100 + i) for i in range(10)
        ]
        assert result["items"][0]["entry"]["observation"]["view_count"] is None
        assert result["items"][0]["author"] == "作者" and result["items"][0]["account_id"] is None
        assert result["metrics"]["videos"] == "10"
        assert feed(c, p, "motion_comic", day, "creator")["items"] == []
        assert feed(c, p, "motion_comic", day - timedelta(days=1), "board")["items"] == []
        assert feed(c, p, "story_short", day, "board")["items"] == []
        assert c.exec_driver_sql(
            "SELECT safe_request FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, tid)
        ).scalar_one() == {"keyword": "漫剧", "offset": 0, "sortType": "_0"}
        # Source title remains mutable; old author comes from the captured response.
        c.exec_driver_sql(
            "UPDATE sources SET enabled=false,lock_version=lock_version+1 WHERE org_id=%s AND id=%s",
            (org, source),
        )
        assert feed(c, p, "motion_comic", day, "board")["total"] == "10"


@pytest.mark.parametrize("restricted", [False, True])
def test_default_search_board_end_to_end(engine, setup, restricted):
    if not restricted:
        return exercise(engine, setup)
    import secrets

    from psycopg import sql

    from app.core.database import build_engine
    from app.core.database_roles import grant_application

    role = "cip_default_" + uuid4().hex
    with engine.begin() as c:
        password = secrets.token_urlsafe(32)
        cursor = c.connection.driver_connection.cursor()
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        grant_application(cursor, role)
    limited = build_engine(engine.url.set(username=role, password=password))
    try:
        exercise(limited, setup)
    finally:
        limited.dispose()
        with engine.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
