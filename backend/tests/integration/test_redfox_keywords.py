from uuid import UUID, uuid4

import httpx
import pytest

from tests.integration.test_collection import prepared
from tests.test_redfox_keywords import payload

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


@pytest.mark.parametrize("restricted", [False, True])
@pytest.mark.parametrize("known_views", [False, True])
def test_keyword_search_not_creator_and_missing_views_cannot_form_board(
    engine, setup, restricted, known_views
):
    if not restricted:
        return exercise(engine, setup, known_views=known_views)
    import secrets

    from psycopg import sql

    from app.core.database import build_engine
    from app.core.database_roles import grant_application

    role = "cip_keyword_test_" + uuid4().hex
    password = secrets.token_urlsafe(32)
    with engine.begin() as c:
        cursor = c.connection.driver_connection.cursor()
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        grant_application(cursor, role)
    limited = build_engine(engine.url.set(username=role, password=password))
    try:
        exercise(limited, setup, known_views=known_views)
    finally:
        limited.dispose()
        with engine.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def exercise(engine, setup, *, known_views=False):
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
        sample = payload()
        if known_views:
            for i, row in enumerate(sample["data"]["list"]):
                row["viewCount"] = 100 + i
            sample["data"]["list"][0]["content"] = "生活教程"
        return httpx.Response(200, json=sample)

    handler = Collect(
        RedFox(lambda: "synthetic", transport=httpx.MockTransport(transport)), min_interval=0
    )
    runner = Runner(engine, {("collect.redfox", VERSION): handler})
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        source = configure_source(
            c, p, "关键词作品：漫剧（非榜单）", "keyword", "漫剧", enabled=True
        )
        job = submit(
            c,
            p,
            CollectionCreate(
                source_id=source,
                provider_connection_id=connection,
                capability_code="douyin.keyword.works",
                max_items=10,
            ),
            str(uuid4()),
            handler,
        )
    assert runner.run(org, UUID(job["task"]["task_id"])) == "succeeded"
    assert len(calls) == 1
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        result = feed(c, p, "motion_comic", shanghai_date(), "creator", 1)
        assert result["total"] == "0" and result["items"] == []
        board = feed(c, p, "motion_comic", shanghai_date(), "board", 1)
        assert board["keyword_ranking_status"] == (
            "ready" if known_views else "insufficient_metrics"
        )
        if known_views:
            assert board["total"] == "9"
            assert board["items"][0]["entry"]["observation"]["view_count"] == "109"
            assert all("漫剧" in x["entry"]["observation"]["description"] for x in board["items"])
        assert board["keyword_works_count"] == "10"
        assert result["metrics"]["videos"] == ("9" if known_views else None)
        if not known_views:
            assert feed(c, p, "motion_comic", shanghai_date(), "board", 1)["items"] == []
        assert result["creators"] == []
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
