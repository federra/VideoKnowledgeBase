"""Only isolated PG/fake model; never network or project data."""

from uuid import uuid4

import pytest

from app.security.errors import Denied
from app.topics import scoring, service
from app.topics.contracts import TopicUpdate, TopicWrite
from app.topics.score_contracts import EvaluateRequest
from app.topics.score_model import KEYS
from tests.integration.test_topics import configured, create, fields, handler_for

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def setup_score(engine, setup, monkeypatch, tmp_path, *, malformed=False, inferred=False):
    from app.model_config.contracts import BindingsWrite
    from app.model_config.service import save_bindings

    p = configured(engine, setup, monkeypatch)
    with engine.begin() as c:
        head = (
            c.exec_driver_sql("SELECT * FROM model_bindings WHERE org_id=%s", (p.org_id,))
            .mappings()
            .one()
        )
        save_bindings(
            c,
            p,
            BindingsWrite(
                business_code="motion_comic",
                expected_lock_version=str(head["lock_version"]),
                bindings={**head["bindings"], "topic_score": head["bindings"]["topic"]},
            ),
            str(uuid4()),
        )
    calls = []
    output = {
        "dimensions": [
            {
                "key": k,
                "score": 3 if i < 5 else (4 if inferred else None),
                "analysis": "合成测试依据",
            }
            for i, k in enumerate(KEYS)
        ],
        "limitations": [],
    }
    if malformed:
        output["dimensions"][0]["score"] = True
    template = handler_for(tmp_path, output, calls)
    return (
        p,
        (scoring.Score if inferred else scoring.LegacyScore)(template.model, template.store),
        calls,
    )


def test_score_once_immutable_and_revision_isolation(engine, setup, monkeypatch, tmp_path):
    from app.tasks.service import Runner

    p, handler, calls = setup_score(engine, setup, monkeypatch, tmp_path)
    t = create(engine, p)
    with engine.begin() as c:
        assert service.topic(c, p, t["id"])["score_model_ready"]
        key = str(uuid4())
        v = scoring.start(c, p, key, t["id"], EvaluateRequest(expected_version=1), handler)
        assert (
            scoring.start(c, p, key, t["id"], EvaluateRequest(expected_version=1), handler)["id"]
            == v["id"]
        )
        assert service.topic(c, p, t["id"])["evaluation_status"] == "pending"
    with engine.begin() as c, pytest.raises(Denied, match="VERSION_CONFLICT"):
        scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
    runner = Runner(engine, {(scoring.KIND, handler.version): handler})
    assert runner.run(p.org_id, v["id"]) == "succeeded"
    runner.run(p.org_id, v["id"])
    assert len(calls) == 1
    with engine.begin() as c:
        done = service.topic(c, p, t["id"])
        assert done["assessment"]["content_total"] == 15
        assert done["assessment"]["market_total"] is None and done["assessment"]["total"] is None
        assert done["evaluation_status"] == "insufficient_evidence"
        aid = done["assessment"]["id"]
        revised = service.revise(
            c, p, uuid4(), t["id"], TopicUpdate(expected_version=1, fields=fields("新版"))
        )
        assert revised["assessment"] is None and revised["evaluation_task"] is None
        assert revised["evaluation_status"] == "needs_review"
        assert scoring.read(c, p, v["id"])["assessment"]["id"] == aid
    with engine.begin() as c, pytest.raises(Exception, match="immutable"):
        c.exec_driver_sql(
            "UPDATE topic_assessments SET body=jsonb_set(body, '{total}', '0') WHERE id=%s", (aid,)
        )


def test_score_stale_revision_fails_without_call(engine, setup, monkeypatch, tmp_path):
    from app.tasks.service import Runner

    p, handler, calls = setup_score(engine, setup, monkeypatch, tmp_path)
    t = create(engine, p)
    with engine.begin() as c:
        v = scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
        service.revise(
            c, p, uuid4(), t["id"], TopicUpdate(expected_version=1, fields=fields("新版"))
        )
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, v["id"])
        == "failed"
    )
    assert calls == []
    with engine.begin() as c:
        assert service.topic(c, p, t["id"])["assessment"] is None


def test_invalid_score_does_not_publish(engine, setup, monkeypatch, tmp_path):
    from app.tasks.service import Runner

    p, handler, calls = setup_score(engine, setup, monkeypatch, tmp_path, malformed=True)
    t = create(engine, p)
    with engine.begin() as c:
        v = scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, v["id"])
        == "failed"
    )
    assert len(calls) == 1
    with engine.begin() as c:
        assert scoring.read(c, p, v["id"])["assessment"] is None
        assert service.topic(c, p, t["id"])["evaluation_status"] == "failed"


def test_score_requires_separate_binding_and_supported_rubric(engine, setup, monkeypatch):
    p = configured(engine, setup, monkeypatch)
    t = create(engine, p)
    with engine.begin() as c:
        assert not service.topic(c, p, t["id"])["score_model_ready"]
    with engine.begin() as c, pytest.raises(Denied, match="MODEL_NOT_CONFIGURED"):
        scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1))
    with engine.begin() as c:
        s = service.create(c, p, uuid4(), TopicWrite(business_code="story_short", fields=fields()))
        assert not s["score_model_ready"]
    with engine.begin() as c, pytest.raises(Denied, match="RUBRIC_UNAVAILABLE"):
        scoring.start(c, p, str(uuid4()), s["id"], EvaluateRequest(expected_version=1))


@pytest.mark.parametrize("tamper", ["topic", "task", "execution", "score", "market", "total"])
def test_database_rejects_misbound_or_invalid_assessments(
    engine, setup, monkeypatch, tmp_path, tamper
):
    from copy import deepcopy

    from app.collection.service import insert
    from app.tasks.service import Runner

    p, handler, _ = setup_score(engine, setup, monkeypatch, tmp_path)
    t = create(engine, p)
    with engine.begin() as c:
        v = scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, v["id"])
        == "succeeded"
    )
    with engine.begin() as c:
        a = (
            c.exec_driver_sql(
                "SELECT * FROM topic_assessments WHERE org_id=%s AND task_id=%s",
                (p.org_id, v["id"]),
            )
            .mappings()
            .one()
        )
        values = {
            key: deepcopy(a[key])
            for key in (
                "topic_id",
                "topic_revision_id",
                "task_id",
                "ai_execution_id",
                "rubric_version",
                "body",
                "created_by",
            )
        }
        if tamper == "topic":
            other = create(engine, p)
            values["topic_id"] = other["id"]
        elif tamper == "task":
            values["task_id"] = uuid4()
        elif tamper == "execution":
            values["ai_execution_id"] = uuid4()
        elif tamper == "score":
            values["body"]["dimensions"][0]["score"] = True
        elif tamper == "market":
            values["body"]["dimensions"][5]["score"] = 5
        else:
            values["body"]["total"] = 15
        with pytest.raises(Exception, match="assessment"), c.begin_nested():
            insert(c, "topic_assessments", p.org_id, **values)


def test_edit_during_score_call_cannot_publish_to_new_head(engine, setup, monkeypatch, tmp_path):
    import httpx

    from app.tasks.service import Runner

    p, handler, calls = setup_score(engine, setup, monkeypatch, tmp_path)
    t = create(engine, p)
    original_transport = handler.model.transport

    def transport(request):
        with engine.begin() as c:
            service.revise(
                c,
                p,
                uuid4(),
                t["id"],
                TopicUpdate(expected_version=1, fields=fields("调用期间新版本")),
            )
        return original_transport.handle_request(request)

    handler.model.transport = httpx.MockTransport(transport)
    with engine.begin() as c:
        v = scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, v["id"])
        == "failed"
    )
    assert len(calls) == 1
    with engine.begin() as c:
        current = service.topic(c, p, t["id"])
        assert current["version"] == 2 and current["assessment"] is None
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM topic_assessments WHERE task_id=%s", (v["id"],)
            ).scalar_one()
            == 0
        )


def test_score_readiness_and_result_allow_content_read_only(engine, setup, monkeypatch, tmp_path):
    from app.security.sessions import MemberPrincipal
    from app.tasks.service import Runner
    from tests.integration.test_security import grant

    p, handler, _ = setup_score(engine, setup, monkeypatch, tmp_path)
    t = create(engine, p)
    with engine.begin() as c:
        v = scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, v["id"])
        == "succeeded"
    )
    with engine.begin() as c:
        member = uuid4()
        c.exec_driver_sql(
            "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,%s)",
            (member, p.org_id, str(member), "只读评分用户"),
        )
        grant(c, p.org_id, p.member_id, member, ["content.read"])
        readonly = MemberPrincipal(p.org_id, member)
        value = service.topic(c, readonly, t["id"])
        assert value["score_model_ready"]
        assert value["assessment"]["content_total"] == 15
        assert scoring.read(c, readonly, v["id"])["assessment"]["content_total"] == 15


def test_inferred_market_scores_publish_with_frozen_v2_provenance(
    engine, setup, monkeypatch, tmp_path
):
    from app.tasks.service import Runner

    p, handler, calls = setup_score(engine, setup, monkeypatch, tmp_path, inferred=True)
    t = create(engine, p)
    with engine.begin() as c:
        v = scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
        task = service.row(c, p, "tasks", v["id"])
        assert task["handler_version"] == "2"
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, v["id"])
        == "succeeded"
    )
    assert len(calls) == 1
    with engine.begin() as c:
        done = service.topic(c, p, t["id"])
        a = done["assessment"]
        assert (
            a["rubric_version"] == "genre-load-v3-inferred" and a["market_basis"] == "ai_inference"
        )
        assert (a["content_total"], a["market_total"], a["total"]) == (15, 20, 35)
        assert done["evaluation_status"] == "scored"
        from app.topics.score_contracts import AssessmentView

        assert AssessmentView.model_validate(a).model_dump()["market_basis"] == "ai_inference"


@pytest.mark.parametrize("legacy", [False, True])
def test_rubric_cannot_cross_bind_handler_version(engine, setup, monkeypatch, tmp_path, legacy):
    from copy import deepcopy

    from app.collection.service import insert
    from app.tasks.service import Runner

    p, handler, _ = setup_score(engine, setup, monkeypatch, tmp_path, inferred=not legacy)
    t = create(engine, p)
    with engine.begin() as c:
        v = scoring.start(c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler)
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, v["id"])
        == "succeeded"
    )
    with engine.begin() as c:
        a = (
            c.exec_driver_sql("SELECT * FROM topic_assessments WHERE task_id=%s", (v["id"],))
            .mappings()
            .one()
        )
        values = {
            k: deepcopy(a[k])
            for k in (
                "topic_id",
                "topic_revision_id",
                "task_id",
                "ai_execution_id",
                "rubric_version",
                "body",
                "created_by",
            )
        }
        values["rubric_version"] = "genre-load-v3-inferred" if legacy else "genre-load-v2"
        with (
            pytest.raises(Exception, match="assessment exact task revision execution mismatch"),
            c.begin_nested(),
        ):
            insert(c, "topic_assessments", p.org_id, **values)


def test_legacy_assessment_unchanged_after_inferred_reevaluation(
    engine, setup, monkeypatch, tmp_path
):
    from app.tasks.service import Runner

    p, legacy, _ = setup_score(engine, setup, monkeypatch, tmp_path)
    t = create(engine, p)
    with engine.begin() as c:
        old = scoring.start(
            c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), legacy
        )
    assert (
        Runner(engine, {(scoring.KIND, legacy.version): legacy}).run(p.org_id, old["id"])
        == "succeeded"
    )
    with engine.begin() as c:
        before = dict(
            c.exec_driver_sql("SELECT * FROM topic_assessments WHERE task_id=%s", (old["id"],))
            .mappings()
            .one()
        )
    calls = []
    output = {
        "dimensions": [{"key": k, "score": 4, "analysis": "AI推断，存在不确定性"} for k in KEYS],
        "limitations": [],
    }
    template = handler_for(tmp_path, output, calls)
    handler = scoring.Score(template.model, template.store)
    with engine.begin() as c:
        new = scoring.start(
            c, p, str(uuid4()), t["id"], EvaluateRequest(expected_version=1), handler
        )
    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(p.org_id, new["id"])
        == "succeeded"
    )
    with engine.begin() as c:
        after = dict(
            c.exec_driver_sql("SELECT * FROM topic_assessments WHERE task_id=%s", (old["id"],))
            .mappings()
            .one()
        )
        assert before == after
        assert scoring.read(c, p, old["id"])["assessment"]["market_basis"] == "unavailable"
        assert scoring.read(c, p, new["id"])["assessment"]["total"] == 40
