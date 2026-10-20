"""Isolated PG; explicitly synthetic provider response; no real comment claims."""

import json
from uuid import uuid4

import httpx
import pytest

from tests.integration.test_collection import payload, prepared, task_id

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def exercise_capture(engine, setup, tmp_path, *, truncated=False, unknown=False):
    from app.collection.comments import Capture, submit_capture
    from app.connectors.tikhub import VERSION, TikHub
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    work = payload()
    work["data"]["list"][0]["videoId"] = "123456789"
    runner, start, org, *rest = prepared(
        engine, setup, response=lambda _: httpx.Response(200, json=work)
    )
    assert runner.run(org, task_id(start())) == "succeeded"
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "status_code": 0,
                    "comments": [
                        {
                            "cid": "comment-1",
                            "aweme_id": "123456789",
                            "text": "期待下一集",
                            "digg_count": 0,
                            "create_time": 1760000000,
                            "user": {"nickname": "采集时昵称"},
                        }
                    ],
                },
            },
        )

    handler = Capture(TikHub(lambda: "offline-token", transport=httpx.MockTransport(transport)))
    with engine.begin() as c:
        entry = c.exec_driver_sql(
            "SELECT id FROM snapshot_entries WHERE org_id=%s", (org,)
        ).scalar_one()
        p = authenticate(c, rest[-1])
        key = str(uuid4())
        accepted = submit_capture(c, p, entry, key, handler)
        assert submit_capture(c, p, entry, key, handler) == accepted
    runner = Runner(engine, {("collect.tikhub-comments", VERSION): handler})
    assert runner.run(org, accepted["task_id"]) == "succeeded"
    assert runner.run(org, accepted["task_id"]) == "ignored"
    assert len(calls) == 1
    from app.security.errors import Denied

    with engine.begin() as c, pytest.raises(Denied):
        submit_capture(c, authenticate(c, rest[-1]), entry, str(uuid4()), handler)
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM comment_evidence WHERE org_id=%s", (org,)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE org_id=%s", (org,)
            ).scalar_one()
            == 1
        )
        value = c.exec_driver_sql(
            "SELECT a.body_text,j.safe_request FROM raw_assets a JOIN collection_jobs j ON j.id=a.collection_job_id WHERE j.org_id=%s AND j.capability_code=%s",
            (org, "douyin.comments.capture"),
        ).one()
        assert json.loads(value[0])["code"] == 200 and "token" not in value[1]
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls cc JOIN collection_jobs j ON j.id=cc.job_id WHERE j.org_id=%s AND j.task_id=%s",
                (org, accepted["task_id"]),
            ).scalar_one()
            == 1
        )

    from app.collection.comment_normalize import NormalizeComments, submit_normalization

    normalizer = NormalizeComments()
    from tests.integration.test_security import grant

    with engine.begin() as c:
        member = c.exec_driver_sql(
            "SELECT member_id FROM auth_sessions WHERE org_id=%s LIMIT 1", (org,)
        ).scalar_one()
        grant(c, org, member, member, ["content.write", "model.configure"])
    with engine.begin() as c:
        raw_id = c.exec_driver_sql(
            "SELECT a.id FROM raw_assets a JOIN collection_jobs j ON j.id=a.collection_job_id WHERE j.task_id=%s",
            (accepted["task_id"],),
        ).scalar_one()
        snap = c.exec_driver_sql(
            "SELECT snapshot_id FROM snapshot_entries WHERE id=%s", (entry,)
        ).scalar_one()
        normalization = submit_normalization(c, authenticate(c, rest[-1]), raw_id, snap, normalizer)
    with engine.begin() as c:
        from app.security.authorization import Authorizer
        from app.tasks.service import input_digest

        t = c.exec_driver_sql("SELECT * FROM tasks WHERE id=%s", (normalization,)).mappings().one()
        frozen = normalizer.freeze(c, t, Authorizer(c, authenticate(c, rest[-1])))
        assert input_digest(t, frozen) == t["input_sha256"]
    norm_runner = Runner(engine, {("comments.normalize", "1"): normalizer})
    with engine.begin() as c:
        t = c.exec_driver_sql("SELECT * FROM tasks WHERE id=%s", (normalization,)).mappings().one()
        norm_runner.validate(c, t)
    state = norm_runner.run(org, normalization)
    with engine.connect() as c:
        code = c.exec_driver_sql(
            "SELECT safe_error_code FROM tasks WHERE id=%s", (normalization,)
        ).scalar_one()
    assert state == "succeeded", code
    with engine.begin() as c:
        assert (
            submit_normalization(c, authenticate(c, rest[-1]), raw_id, snap, normalizer)
            == normalization
        )
        value = c.exec_driver_sql(
            "SELECT body_text,username,like_count FROM comment_evidence WHERE org_id=%s", (org,)
        ).one()
        assert value == ("期待下一集", "采集时昵称", 0)

    from pydantic import SecretStr

    from app.ai.deepseek import DeepSeek
    from app.ai.feedback_task import FeedbackTask, submit_feedback
    from app.storage.local import LocalStore

    model_calls = []

    def model_transport(request):
        model_calls.append(request)
        if unknown:
            raise httpx.ReadTimeout("private timeout", request=request)
        source = json.loads(json.loads(request.content)["messages"][1]["content"])
        output = {
            "result_state": "completed",
            "summary": "一条评论期待后续",
            "claims": [
                {
                    "kind": "emotion",
                    "claim_key": "expect",
                    "text": "期待",
                    "trigger": "后续剧情",
                    "comment_ids": [source["comments"][0]["id"]],
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "id": "offline-model",
                "choices": [
                    {
                        "finish_reason": "length" if truncated else "stop",
                        "message": {"content": json.dumps(output)},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40},
            },
        )

    store = LocalStore(tmp_path / "model-files")
    try:
        ai = FeedbackTask(
            DeepSeek(
                lambda: SecretStr("offline-key"), transport=httpx.MockTransport(model_transport)
            ),
            store,
        )
        with engine.begin() as c:
            ai_task = submit_feedback(c, authenticate(c, rest[-1]), raw_id, snap, ai)
            assert submit_feedback(c, authenticate(c, rest[-1]), raw_id, snap, ai) == ai_task
        state = Runner(engine, {("audience.feedback", "1"): ai}).run(org, ai_task)
        if unknown:
            assert state == "failed" and len(model_calls) == 1
            with engine.connect() as c:
                from app.tasks.service import external_calls, unresolved_calls

                assert unresolved_calls(c, ai_task) == external_calls(c, ai_task) == 1
                assert (
                    c.exec_driver_sql(
                        "SELECT safe_error_code FROM tasks WHERE id=%s", (ai_task,)
                    ).scalar_one()
                    == "EXTERNAL_RESULT_UNKNOWN"
                )
            return
        if truncated:
            assert state == "failed" and len(model_calls) == 1
            with engine.connect() as c:
                execution = (
                    c.exec_driver_sql("SELECT * FROM ai_executions WHERE task_id=%s", (ai_task,))
                    .mappings()
                    .one()
                )
                assert (
                    c.exec_driver_sql(
                        "SELECT safe_error_code FROM tasks WHERE id=%s", (ai_task,)
                    ).scalar_one()
                    == "INVALID_RESPONSE"
                )
                from app.tasks.service import external_calls, unresolved_calls

                assert unresolved_calls(c, ai_task) == 0
                assert external_calls(c, ai_task) == 1
                assert execution["output_file_id"] is not None
                assert (
                    execution["input_tokens"],
                    execution["output_tokens"],
                    execution["provider_request_id"],
                ) == (100, 40, "offline-model")
                assert (
                    c.exec_driver_sql(
                        "SELECT count(*) FROM feedback_snapshots WHERE task_id=%s", (ai_task,)
                    ).scalar_one()
                    == 0
                )
                with store.open(org, execution["output_file_id"]) as stream:
                    assert json.loads(stream.read())["result_state"] == "completed"
            return
        assert state == "succeeded"
        assert len(model_calls) == 1
        with engine.begin() as c:
            from app.intelligence.feedback import entry_feedback

            result = entry_feedback(
                c,
                authenticate(c, rest[-1]),
                entry,
                "motion_comic",
                c.exec_driver_sql(
                    "SELECT business_date FROM intelligence_snapshots WHERE id=%s", (snap,)
                ).scalar_one(),
            )
            assert result["status"] == "ready" and result["classified_count"] == 1
            assert result["comments"][0]["username"] == "采集时昵称"
            assert c.exec_driver_sql(
                "SELECT input_tokens,output_tokens FROM ai_executions WHERE task_id=%s", (ai_task,)
            ).one() == (100, 40)
        from tests.integration.test_handoffs import verify_handoff

        verify_handoff(engine, org, member, rest[-1], entry, result)

        from app.intelligence.insight import InsightTask, latest_insight, submit_insight

        insight = InsightTask()
        with engine.begin() as c:
            task = submit_insight(c, authenticate(c, rest[-1]), result["feedback_id"], insight)
        assert (
            Runner(engine, {("intelligence.insight", "1"): insight}).run(org, task) == "succeeded"
        )
        with engine.begin() as c:
            from app.intelligence.service import feed

            day = c.exec_driver_sql(
                "SELECT business_date FROM intelligence_snapshots WHERE id=%s", (snap,)
            ).scalar_one()
            saved = latest_insight(c, authenticate(c, rest[-1]), "motion_comic", day)
            assert saved["sample_count"] == 1 and saved["emotions"][0]["percent"] == 100
            assert (
                feed(c, authenticate(c, rest[-1]), "motion_comic", day, "creator")["insight"]["id"]
                == saved["id"]
            )
            assert latest_insight(c, authenticate(c, rest[-1]), "story_short", day) is None
            c.exec_driver_sql(
                "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','test')",
                (org, raw_id),
            )
            assert latest_insight(c, authenticate(c, rest[-1]), "motion_comic", day) is None
    finally:
        store.close()


def test_capture_absent_entry_fails_before_network(engine, setup):
    from uuid import uuid4

    from app.collection.comments import Capture, submit_capture
    from app.connectors.tikhub import TikHub
    from app.security.errors import Denied
    from app.security.sessions import authenticate

    runner, start, org, *rest = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, rest[-1])
        with pytest.raises(Denied):
            submit_capture(c, p, uuid4(), str(uuid4()), Capture(TikHub(lambda: None)))


@pytest.mark.parametrize("restricted", [False, True])
def test_comment_capture_durable_and_restricted(engine, setup, restricted, tmp_path):
    if not restricted:
        return exercise_capture(engine, setup, tmp_path)
    import secrets

    from psycopg import sql

    from app.core.database import build_engine
    from app.core.database_roles import grant_application

    role = "cip_comment_probe_" + uuid4().hex
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
        exercise_capture(limited, setup, tmp_path)
    finally:
        limited.dispose()
        with engine.begin() as c:
            cursor = c.connection.driver_connection.cursor()
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_truncated_model_output_is_durably_saved_without_feedback(engine, setup, tmp_path):
    exercise_capture(engine, setup, tmp_path, truncated=True)


def test_unknown_model_timeout_remains_unresolved_without_retry(engine, setup, tmp_path):
    exercise_capture(engine, setup, tmp_path, unknown=True)
