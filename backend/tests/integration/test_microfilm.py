import json
from datetime import UTC, datetime

import pytest

from app.collection.microfilm import Microfilm, run
from app.connectors.redfox import Reply
from app.security.sessions import authenticate
from tests.integration.test_feed_refresh import authorize
from tests.test_douyin_posts import NOW, post
from tests.test_douyin_search import wrapped

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


@pytest.mark.parametrize(
    "mode", ["complete", "partial", "blocked", "bad_cursor", "cooldown", "verification"]
)
def test_microfilm_prefix_order_comment_bounds_and_two_failure_ceiling(
    engine, setup, mode, monkeypatch
):
    authorize(engine, setup)
    calls = []

    class Fake:
        before_request = None

        def __init__(self, **kw):
            pass

        def __enter__(self):
            if mode == "cooldown":
                from app.connectors.redfox import AdapterError

                raise AdapterError("SOURCE_UNAVAILABLE")
            return self

        def __exit__(self, *args):
            pass

        def fetch(self, kind, target, cursor, search_id):
            if self.before_request:
                self.before_request()
            calls.append((kind, target, cursor))
            if mode == "verification":
                return Reply(
                    200,
                    None,
                    "invalid_shape",
                    '{"title":"验证码中间页"}',
                    datetime.now(UTC),
                    error="SOURCE_VERIFICATION_REQUIRED",
                )
            if mode == "blocked" or mode == "partial" and kind == "search" and cursor > 0:
                return Reply(
                    403,
                    None,
                    "http_error",
                    "blocked",
                    datetime.now(UTC),
                    error="SOURCE_UNAVAILABLE",
                )
            if kind == "search":
                value = wrapped(
                    [post(i, NOW, i) for i in range(cursor + 1, min(cursor + 21, 51))],
                    offset=cursor,
                    cursor=cursor + 20,
                    more=0 if cursor == 40 else 1,
                )
            else:
                value = {
                    "kind": "comments",
                    "parameters": {"aweme_id": target, "cursor": "0"},
                    "body": {
                        "status_code": 0,
                        "has_more": 0,
                        "cursor": 20,
                        "comments": [
                            {
                                "cid": target + str(i),
                                "aweme_id": target,
                                "text": f"评论{i}",
                                "create_time": 1700000000,
                                "digg_count": i,
                                "user": {"nickname": "观众"},
                            }
                            for i in range(20)
                        ],
                    },
                }
            if mode == "bad_cursor" and kind == "search" and cursor > 0:
                value["body"]["cursor"] = cursor
            return Reply(200, None, "success", json.dumps(value), datetime.now(UTC))

    with engine.begin() as c:
        p = authenticate(c, setup[2])
    result = run(engine, p, one_off_retry=True, handler=Microfilm(Fake))
    expected = {
        "complete": 50,
        "partial": 20,
        "blocked": 0,
        "bad_cursor": 20,
        "cooldown": 0,
        "verification": 0,
    }[mode]
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id WHERE s.org_id=%s",
                (p.org_id,),
            ).scalar_one()
            == expected
        )
        assert c.exec_driver_sql(
            "SELECT count(*) FROM comment_evidence WHERE org_id=%s", (p.org_id,)
        ).scalar_one() == (750 if mode == "complete" else 0)
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM sources WHERE org_id=%s AND business_code='story_short' AND enabled",
                (p.org_id,),
            ).scalar_one()
            == 0
        )
        assert c.exec_driver_sql(
            "SELECT count(*) FROM collection_calls WHERE org_id=%s AND http_status=403", (p.org_id,)
        ).scalar_one() == (2 if mode in ("partial", "blocked") else 0)
    if expected:
        from app.intelligence.feedback import entry_feedback
        from app.intelligence.service import feed, shanghai_date

        with engine.begin() as c:
            p = authenticate(c, setup[2])
            from sqlalchemy import event
            statements = []
            def count_queries(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)
            event.listen(c, 'before_cursor_execute', count_queries)
            data = feed(c, p, "story_short", shanghai_date(), lane="board")
            event.remove(c, 'before_cursor_execute', count_queries)
            assert len(statements) < 500  # A ten-card preview must not reread all 50 comment pages ten times.

            assert data["total"] == str(expected)
            assert [v["entry"]["observation"]["platform_id"] for v in data["items"]] == [
                str(i) for i in range(1, 11)
            ]
            sample = entry_feedback(
                c, p, data["items"][0]["entry"]["id"], "story_short", shanghai_date()
            )
            assert sample["sample_count"] == (15 if mode == "complete" else None)
    assert result["state"] == (
        "failed" if mode in ("blocked", "cooldown", "verification") else "succeeded"
    )
    if mode == "cooldown":
        assert result["error"] == "SOURCE_UNAVAILABLE"
    if mode == "verification":
        assert result["error"] == "SOURCE_VERIFICATION_REQUIRED"
    assert (
        len(calls)
        == {
            "complete": 53,
            "partial": 3,
            "blocked": 2,
            "bad_cursor": 3,
            "cooldown": 0,
            "verification": 1,
        }[mode]
    )
    if mode == "complete":
        with engine.connect() as c:
            frozen_key = c.exec_driver_sql(
                "SELECT idempotency_key FROM tasks WHERE id=%s", (result["task_id"],)
            ).scalar_one()
        replay = run(engine, p, key=frozen_key, one_off_retry=True, handler=Microfilm(Fake))
        assert replay["state"] == "succeeded"
        assert len(calls) == 53
        from app.collection import microfilm
        from app.connectors import douyin_search

        with monkeypatch.context() as ctx:
            ctx.setattr(microfilm, "BOARD", "another-story-board")
            ctx.setattr(douyin_search, "CAPABILITY", "another.story.board")
            assert (
                run(engine, p, one_off_retry=True, handler=Microfilm(Fake))["state"] == "succeeded"
            )
        with engine.begin() as c:
            p = authenticate(c, setup[2])
            isolated = feed(c, p, "story_short", shanghai_date(), lane="board")
            assert isolated["total"] == "50"


@pytest.mark.parametrize("phase", ["search", "comments", "after_comment"])
def test_human_verification_keeps_acquired_prefix_and_marks_partial(engine, setup, phase):
    authorize(engine, setup)
    calls = []

    class Fake:
        before_request = None

        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def fetch(self, kind, target, cursor, search_id):
            if self.before_request:
                self.before_request()
            calls.append((kind, target, cursor))
            challenge = (
                (phase == "search" and cursor > 0)
                or (phase == "comments" and kind == "comments")
                or (phase == "after_comment" and kind == "comments" and target == "2")
            )
            if challenge:
                return Reply(
                    200,
                    None,
                    "invalid_shape",
                    '{"title":"验证码中间页"}',
                    datetime.now(UTC),
                    error="SOURCE_VERIFICATION_REQUIRED",
                )
            if kind == "search":
                data = wrapped(
                    [post(i, NOW, i) for i in range(1, 21)],
                    offset=0,
                    cursor=20,
                    more=1 if phase == "search" else 0,
                )
            else:
                data = {
                    "kind": "comments",
                    "parameters": {"aweme_id": target, "cursor": "0"},
                    "body": {
                        "status_code": 0,
                        "has_more": 0,
                        "cursor": 15,
                        "comments": [
                            {
                                "cid": target + str(i),
                                "aweme_id": target,
                                "text": f"原文{i}",
                                "create_time": 1700000000,
                                "digg_count": 1,
                            }
                            for i in range(15)
                        ],
                    },
                }
            return Reply(200, None, "success", json.dumps(data), datetime.now(UTC))

    with engine.begin() as c:
        p = authenticate(c, setup[2])
    result = run(engine, p, one_off_retry=True, handler=Microfilm(Fake))
    assert result["state"] == "succeeded"
    assert result["outcome"] == "insufficient_evidence"
    assert result.get("verification_required") is True
    assert len(calls) == (3 if phase == "after_comment" else 2)
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id WHERE s.org_id=%s",
                (p.org_id,),
            ).scalar_one()
            == 20
        )
        assert c.exec_driver_sql(
            "SELECT count(*) FROM comment_evidence WHERE org_id=%s", (p.org_id,)
        ).scalar_one() == (15 if phase == "after_comment" else 0)
