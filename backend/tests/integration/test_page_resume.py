"""Same-day audited API reuse never forges a second collection call."""

import json
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

import pytest

from app.collection.microfilm import Microfilm, run
from app.connectors.redfox import Reply
from app.security.sessions import authenticate
from tests.integration.test_feed_refresh import authorize
from tests.test_douyin_posts import NOW, post
from tests.test_douyin_search import wrapped

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


class Prefix:
    before_request = None
    calls: ClassVar[list] = []

    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def fetch(self, kind, target, cursor, search_id):
        self.calls.append((kind, target, cursor))
        if kind != "search" or cursor:
            return Reply(
                403, None, "http_error", "denied", datetime.now(UTC), error="SOURCE_UNAVAILABLE"
            )
        return Reply(
            200,
            None,
            "success",
            json.dumps(
                wrapped([post(i, NOW, i) for i in range(1, 21)], offset=0, cursor=20, more=1)
            ),
            datetime.now(UTC),
        )


class Remaining(Prefix):
    calls: ClassVar[list] = []

    def fetch(self, kind, target, cursor, search_id):
        self.calls.append((kind, target, cursor))
        assert (kind, cursor) != ("search", 0), "successful source page must not be fetched twice"
        if kind == "search":
            value = wrapped(
                [post(i, NOW, i) for i in range(cursor + 1, min(cursor + 21, 51))],
                offset=cursor,
                cursor=cursor + 20,
                more=int(cursor < 40),
            )
        else:
            value = {
                "kind": "comments",
                "parameters": {"aweme_id": target, "cursor": str(cursor)},
                "body": {
                    "status_code": 0,
                    "has_more": 0,
                    "cursor": 15,
                    "comments": [
                        {
                            "cid": target + str(i),
                            "aweme_id": target,
                            "text": "实测评论",
                            "create_time": 1700000000,
                            "digg_count": i,
                            "user": {"nickname": "观众"},
                        }
                        for i in range(15)
                    ],
                },
            }
        return Reply(200, None, "success", json.dumps(value), datetime.now(UTC))


def parent(engine, setup):
    authorize(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
    result = run(engine, p, handler=Microfilm(Prefix))
    with engine.begin() as c:
        job = c.exec_driver_sql(
            "SELECT id FROM collection_jobs WHERE task_id=%s", (UUID(result["task_id"]),)
        ).scalar_one()
    return p, job


def test_resume_uses_original_raw_without_duplicate_calls_and_keeps_trace(engine, setup):
    from app.collection.page_resume import start_resume

    p, job = parent(engine, setup)
    Remaining.calls = []
    with engine.begin() as c:
        raw = c.exec_driver_sql(
            "SELECT r.id FROM raw_assets r JOIN collection_calls cc ON cc.id=r.collection_call_id WHERE r.collection_job_id=%s AND cc.outcome='success'",
            (job,),
        ).scalar_one()
        before = c.exec_driver_sql(
            "SELECT count(*) FROM collection_calls WHERE job_id=%s", (job,)
        ).scalar_one()
    result = start_resume(engine, p, job, key="resume/" + str(uuid4()), connector_factory=Remaining)
    assert result["state"] == "succeeded", result
    with engine.begin() as c:
        new = c.exec_driver_sql(
            "SELECT id FROM collection_jobs WHERE task_id=%s", (UUID(result["task_id"]),)
        ).scalar_one()
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE job_id=%s", (job,)
            ).scalar_one()
            == before
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE job_id=%s", (new,)
            ).scalar_one()
            == len(Remaining.calls)
            == 52
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id JOIN content_observations o ON o.id=e.content_observation_id WHERE s.job_id=%s AND o.raw_asset_id=%s",
                (new, raw),
            ).scalar_one()
            == 20
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM task_inputs WHERE task_id=%s AND role='collection_page_reuse' AND raw_asset_id=%s",
                (UUID(result["task_id"]), raw),
            ).scalar_one()
            == 1
        )
        from app.intelligence.feedback import entry_feedback
        from app.intelligence.service import feed, shanghai_date

        visible = feed(c, p, "story_short", shanghai_date(), lane="board")
        assert visible["total"] == "50"
        first = visible["items"][0]["entry"]
        assert first["observation"]["display_name"] == "视频1"
        assert first["observation"]["like_count"] == "1"
        assert (
            entry_feedback(c, p, first["id"], "story_short", shanghai_date())["sample_count"] == 15
        )


def test_resume_rejects_failed_raw(engine, setup):
    from app.collection.page_resume import start_resume
    from app.tasks.service import TaskError

    p, job = parent(engine, setup)
    with engine.begin() as c:
        raw = c.exec_driver_sql(
            "SELECT r.id FROM raw_assets r JOIN collection_calls cc ON cc.id=r.collection_call_id WHERE r.collection_job_id=%s AND cc.outcome<>'success' LIMIT 1",
            (job,),
        ).scalar_one()
    with pytest.raises(TaskError, match="INVALID_INPUT"):
        start_resume(
            engine,
            p,
            job,
            key="invalid/" + str(uuid4()),
            raw_ids=[raw],
            connector_factory=Remaining,
        )


def test_resume_reuses_completed_comment_sample_and_latest_manifest(engine, setup):
    from app.collection.page_resume import start_resume

    authorize(engine, setup)

    class CommentPrefix(Remaining):
        calls: ClassVar[list] = []

        def fetch(self, kind, target, cursor, search_id):
            if kind == "search":
                value = wrapped([post(i, NOW, i) for i in range(1, 4)], offset=0, cursor=20, more=0)
                return Reply(200, None, "success", json.dumps(value), datetime.now(UTC))
            if target != "1":
                return Reply(
                    403, None, "http_error", "denied", datetime.now(UTC), error="SOURCE_UNAVAILABLE"
                )
            return super().fetch(kind, target, cursor, search_id)

    with engine.begin() as c:
        p = authenticate(c, setup[2])
    previous = run(engine, p, handler=Microfilm(CommentPrefix))
    with engine.begin() as c:
        job = c.exec_driver_sql(
            "SELECT id FROM collection_jobs WHERE task_id=%s", (UUID(previous["task_id"]),)
        ).scalar_one()
        comment_raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM comment_evidence WHERE org_id=%s LIMIT 1", (p.org_id,)
        ).scalar_one()
    Remaining.calls = []
    key = "comments-resume/" + str(uuid4())
    result = start_resume(engine, p, job, key=key, connector_factory=Remaining)
    assert result["state"] == "succeeded", result
    assert len(Remaining.calls) == 2
    assert all(kind == "comments" and target != "1" for kind, target, cursor in Remaining.calls)
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM comment_evidence WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 45
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM comment_evidence WHERE raw_asset_id=%s", (comment_raw,)
            ).scalar_one()
            == 15
        )
        manifest = json.loads(
            c.exec_driver_sql(
                "SELECT r.body_text FROM task_outputs o JOIN raw_assets r ON r.id=o.raw_asset_id WHERE o.task_id=%s AND o.role='microfilm_manifest'",
                (UUID(result["task_id"]),),
            ).scalar_one()
        )
        assert manifest["comments"]["1"] == [str(comment_raw)]
        from app.intelligence.feedback import entry_feedback
        from app.intelligence.microfilm import sample_for_entry
        from app.intelligence.service import feed, shanghai_date

        visible = feed(c, p, "story_short", shanghai_date(), lane="board")
        assert visible["total"] == "3"
        first_entry = visible["items"][0]["entry"]
        assert first_entry["observation"]["display_name"] == "视频1"
        sample = sample_for_entry(c, p, first_entry["id"], "story_short", shanghai_date())
        original_ids = set(
            c.exec_driver_sql(
                "SELECT id FROM comment_evidence WHERE raw_asset_id=%s", (comment_raw,)
            ).scalars()
        )
        assert {v["id"] for v in sample} == original_ids and len(sample) == 15
        feedback = entry_feedback(c, p, first_entry["id"], "story_short", shanghai_date())
        assert (
            feedback["sample_count"] == 15
            and {v["id"] for v in feedback["comments"]} == original_ids
        )
    again = start_resume(engine, p, job, key=key, connector_factory=Remaining)
    assert again == result and len(Remaining.calls) == 2


def test_resume_rejects_cross_day_before_new_calls(engine, setup, monkeypatch):
    from datetime import timedelta

    from app.collection import page_resume
    from app.tasks.service import TaskError

    p, job = parent(engine, setup)
    current = page_resume.shanghai_date
    monkeypatch.setattr(
        page_resume,
        "shanghai_date",
        lambda value=None: current(value) if value else current() + timedelta(days=1),
    )
    with pytest.raises(TaskError, match="DATE_WINDOW_MISMATCH"):
        page_resume.start_resume(
            engine, p, job, key="cross-day/" + str(uuid4()), connector_factory=Remaining
        )


def test_creator_resume_continues_nonzero_cursor_with_original_provenance(
    engine, setup, monkeypatch
):
    from datetime import timedelta

    from app.collection.page_resume import start_resume
    from app.intelligence import creator_posts
    from app.intelligence.creator_contracts import CreatorBatch
    from app.intelligence.creators import save
    from app.intelligence.refresh import start
    from app.intelligence.refresh_worker import runtime
    from tests.test_douyin_posts import page

    authorize(engine, setup)
    now = datetime.now(UTC)

    class Creator:
        before_request = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def resolve(self, url):
            return {
                "status": 200,
                "body": json.dumps(
                    {
                        "status_code": 0,
                        "user": {"uid": "123456", "sec_uid": "MS4w_test", "nickname": "博主"},
                    }
                ),
                "error": None,
            }

        def fetch(self, sec, cursor):
            if cursor:
                return Reply(
                    403, None, "http_error", "denied", datetime.now(UTC), error="SOURCE_UNAVAILABLE"
                )
            return Reply(
                200,
                None,
                "success",
                json.dumps(page([post(1, now - timedelta(hours=1), 9)], cursor=100, more=1)),
                datetime.now(UTC),
            )

    monkeypatch.setattr(creator_posts, "connector_factory", Creator)
    monkeypatch.setattr("app.intelligence.creator_resolution.PROFILE_INTERVAL", 0)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        save(
            c,
            p,
            CreatorBatch(
                business_code="story_short", links="https://www.douyin.com/user/MS4w_test"
            ),
            str(uuid4()),
        )
        batch = start(c, p, "story_short", str(uuid4()), creators_only=True)
    assert runtime(engine).run(p.org_id, UUID(batch["task_id"])) == "succeeded"
    with engine.begin() as c:
        job = c.exec_driver_sql(
            "SELECT id FROM collection_jobs WHERE org_id=%s AND capability_code='douyin.creator.posts'",
            (p.org_id,),
        ).scalar_one()
        original_raw = c.exec_driver_sql(
            "SELECT r.id FROM raw_assets r JOIN collection_calls cc ON cc.id=r.collection_call_id WHERE r.collection_job_id=%s AND cc.outcome='success'",
            (job,),
        ).scalar_one()

    class Continuation(Creator):
        calls: ClassVar[list] = []

        def fetch(self, sec, cursor):
            self.calls.append(cursor)
            assert cursor == 100
            return Reply(
                200,
                None,
                "success",
                json.dumps(page([post(2, now - timedelta(hours=2), 20)])),
                datetime.now(UTC),
            )

    connector = Continuation()
    result = start_resume(engine, p, job, key="creator-resume/" + str(uuid4()), connector=connector)
    assert result["state"] == "succeeded", result
    assert connector.calls == [100]
    with engine.begin() as c:
        new = c.exec_driver_sql(
            "SELECT id FROM collection_jobs WHERE task_id=%s", (UUID(result["task_id"]),)
        ).scalar_one()
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE job_id=%s", (new,)
            ).scalar_one()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id JOIN content_observations o ON o.id=e.content_observation_id WHERE s.job_id=%s AND o.raw_asset_id=%s",
                (new, original_raw),
            ).scalar_one()
            == 1
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id WHERE s.job_id=%s",
                (new,),
            ).scalar_one()
            == 2
        )
        from app.intelligence.service import feed, shanghai_date

        visible = feed(c, p, "story_short", shanghai_date(), lane="creator")
        assert visible["total"] == "2"
        assert [v["entry"]["observation"]["like_count"] for v in visible["items"]] == ["20", "9"]
        assert [v["entry"]["observation"]["display_name"] for v in visible["items"]] == [
            "视频2",
            "视频1",
        ]
        assert [v["entry"]["observation"]["description"] for v in visible["items"]] == [
            "视频2",
            "视频1",
        ]


def test_resume_wrong_source_and_kind_denied_before_request(engine, setup):
    from app.collection.page_resume import _checked, submit_resume
    from app.collection.service import get
    from app.security.authorization import Authorizer
    from app.tasks.service import TaskError

    p, job_id = parent(engine, setup)
    with engine.begin() as c:
        job = get(c, "collection_jobs", p.org_id, job_id)
        raw = c.exec_driver_sql(
            "SELECT r.id FROM raw_assets r JOIN collection_calls cc ON cc.id=r.collection_call_id WHERE r.collection_job_id=%s AND cc.outcome='success'",
            (job_id,),
        ).scalar_one()
        with pytest.raises(TaskError, match="INVALID_INPUT"):
            _checked(c, p.org_id, {**job, "source_id": uuid4()}, [str(raw)], Authorizer(c, p))
        tid, _, handler = submit_resume(
            c, p, job_id, key="wrong-kind/" + str(uuid4()), connector_factory=Remaining
        )
        task = get(c, "tasks", p.org_id, tid)
        with pytest.raises(TaskError, match="INVALID_INPUT"):
            handler.freeze(c, {**task, "kind": "collect.microfilm"}, Authorizer(c, p))
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls cc JOIN collection_jobs j ON j.id=cc.job_id WHERE j.task_id=%s",
                (tid,),
            ).scalar_one()
            == 0
        )
