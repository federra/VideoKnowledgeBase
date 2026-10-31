"""Synthetic isolated PG topic commands and one-call fake model publication."""

import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.security.errors import Denied
from app.security.sessions import MemberPrincipal, authenticate
from app.topics import service
from app.topics.contracts import (
    GenerateRequest,
    GenerationSave,
    SparkWrite,
    TopicFields,
    TopicHandoff,
    TopicSelect,
    TopicUpdate,
    TopicWrite,
)
from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def fields(title="合成测试题"):
    return TopicFields(
        title=title,
        audience="测试观众",
        logline="测试主角追索线索，面临代价。",
        character_settings="主角寻求真相，对手隐藏秘密。",
        global_rhythm="发现线索→冲突→付出代价。",
    )


def principal(engine, setup):
    with engine.begin() as c:
        grant(
            c,
            setup[0],
            setup[1],
            setup[1],
            ["content.read", "content.write", "content.export", "evidence.read", "model.configure"],
        )
        return authenticate(c, setup[2])


def create(engine, p, title="合成测试题"):
    with engine.begin() as c:
        return service.create(
            c, p, uuid4(), TopicWrite(business_code="motion_comic", fields=fields(title))
        )


def test_topic_manual_idempotence_nochange_and_cas(engine, setup):
    p = principal(engine, setup)
    key = uuid4()
    body = TopicWrite(business_code="motion_comic", fields=fields())
    with engine.begin() as c:
        original = service.create(c, p, key, body)
        assert service.create(c, p, key, body)["id"] == original["id"]
        assert original["evaluation_status"] == "not_evaluated"
        same = service.revise(
            c, p, uuid4(), original["id"], TopicUpdate(expected_version=1, fields=fields())
        )
        assert same["version"] == 1 and len(same["history"]) == 1
    with engine.begin() as c:
        updated = service.revise(
            c,
            p,
            uuid4(),
            original["id"],
            TopicUpdate(expected_version=1, fields=fields("修改标题")),
        )
        assert updated["version"] == 2 and updated["evaluation_status"] == "needs_review"
        assert len(updated["history"]) == 2
        assert updated["history"][1]["fields"]["title"] == original["fields"]["title"]
    with engine.begin() as c, pytest.raises(Denied, match="VERSION_CONFLICT"):
        service.revise(
            c,
            p,
            uuid4(),
            original["id"],
            TopicUpdate(expected_version=1, fields=fields("迟到编辑")),
        )


def test_selected_version_and_handoff_are_exact(engine, setup):
    p = principal(engine, setup)
    original = create(engine, p)
    with engine.begin() as c:
        service.choose(c, p, uuid4(), original["id"], TopicSelect(expected_version=1))
        key = uuid4()
        handoff = service.handoff(
            c, p, key, original["id"], TopicHandoff(expected_version=1, method="copy")
        )
        assert (
            service.handoff(
                c, p, key, original["id"], TopicHandoff(expected_version=1, method="copy")
            )
            == handoff
        )
        service.revise(
            c,
            p,
            uuid4(),
            original["id"],
            TopicUpdate(expected_version=1, fields=fields("生产后修改")),
        )
    with engine.begin() as c, pytest.raises(Denied, match="VERSION_CONFLICT"):
        service.handoff(
            c, p, uuid4(), original["id"], TopicHandoff(expected_version=2, method="export")
        )
    with engine.begin() as c:
        service.choose(c, p, uuid4(), original["id"], TopicSelect(expected_version=2))
        service.handoff(
            c, p, uuid4(), original["id"], TopicHandoff(expected_version=2, method="export")
        )
        versions = (
            c.exec_driver_sql(
                "SELECT r.version_no FROM topic_handoffs h JOIN topic_revisions r "
                "ON r.org_id=h.org_id AND r.id=h.topic_revision_id "
                "WHERE h.org_id=%s AND h.topic_id=%s ORDER BY h.created_at",
                (p.org_id, original["id"]),
            )
            .scalars()
            .all()
        )
        assert versions == [1, 2]


def test_business_scoped_authorization_and_crossorg(engine, setup):
    p = principal(engine, setup)
    original = create(engine, p)
    with engine.begin() as c:
        other_member = uuid4()
        c.exec_driver_sql(
            "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,%s)",
            (other_member, p.org_id, str(other_member), "scoped tester"),
        )
        grant(c, p.org_id, p.member_id, other_member, ["content.read"], "business", "story_short")
        scoped = MemberPrincipal(p.org_id, other_member)
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            service.topic(c, scoped, original["id"])
        other_org_member = c.exec_driver_sql(
            "SELECT id FROM members WHERE org_id=%s LIMIT 1", (setup[3],)
        ).scalar_one()
        with pytest.raises(Denied, match="NOT_FOUND"):
            service.topic(c, MemberPrincipal(setup[3], other_org_member), original["id"])


def test_personal_sparks_version_and_private_lineage(engine, setup):
    p = principal(engine, setup)
    with engine.begin() as c:
        spark = service.save_spark(c, p, uuid4(), SparkWrite(text="私有闪念"))
        unchanged = service.save_spark(
            c, p, uuid4(), SparkWrite(id=spark["id"], expected_version=1, text="私有闪念")
        )
        assert unchanged["version"] == 1
        assert (
            service.save_spark(
                c, p, uuid4(), SparkWrite(id=spark["id"], expected_version=1, text="新版闪念")
            )["version"]
            == 2
        )
        revision = c.exec_driver_sql(
            "SELECT id FROM topic_spark_revisions WHERE org_id=%s AND spark_id=%s AND version_no=1",
            (p.org_id, spark["id"]),
        ).scalar_one()
        topic = service.add(
            c,
            p,
            "motion_comic",
            fields().model_dump(),
            origin="brainstorm",
            source_refs={"sparks": [{"id": str(spark["id"]), "revision_id": str(revision)}]},
        )
        assert service.topic(c, p, topic)["source_refs"]["sparks"][0]["revision_id"] == str(
            revision
        )
        other = uuid4()
        c.exec_driver_sql(
            "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,%s)",
            (other, p.org_id, str(other), "other tester"),
        )
        grant(c, p.org_id, p.member_id, other, ["content.read", "content.write"])
        other_p = MemberPrincipal(p.org_id, other)
        assert service.sparks(c, other_p)["items"] == []
        with pytest.raises(Denied, match="NOT_FOUND"):
            service.spark(c, other_p, spark["id"])
        with pytest.raises(Denied, match="NOT_FOUND"):
            service.topic(c, other_p, topic)
        assert service.listing(c, other_p, "motion_comic", "candidate", 1)["total"] == "0"
    with engine.begin() as c, pytest.raises(Denied, match="VERSION_CONFLICT"):
        service.save_spark(
            c, p, uuid4(), SparkWrite(id=spark["id"], expected_version=1, text="迟到修改")
        )


def configured(engine, setup, monkeypatch):
    from app.model_config.contracts import BindingsWrite
    from app.model_config.service import save_bindings, save_source
    from tests.integration.test_model_config import source

    p = principal(engine, setup)
    monkeypatch.setattr(settings, "deepseek_key", SecretStr("isolated-only-never-real"))
    with engine.begin() as c:
        saved = save_source(c, p, source(), str(uuid4()))
        save_bindings(
            c,
            p,
            BindingsWrite(
                business_code="motion_comic",
                expected_lock_version="0",
                bindings={"topic": saved["id"]},
            ),
            str(uuid4()),
        )
    return p


def handler_for(tmp_path, output, calls):
    from app.model_config import ConfiguredModel
    from app.storage.local import LocalStore
    from app.topics.generation import Generate

    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "isolated-topic-response",
                "usage": {"prompt_tokens": 20, "completion_tokens": 30},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(output, ensure_ascii=False)},
                    }
                ],
            },
        )

    return Generate(
        ConfiguredModel(lookup=lambda _: ["8.8.8.8"], transport=httpx.MockTransport(transport)),
        LocalStore(tmp_path / "objects"),
    )


def count_cards(engine, org):
    with engine.connect() as c:
        return c.exec_driver_sql(
            "SELECT count(*) FROM topic_cards WHERE org_id=%s", (org,)
        ).scalar_one()


def test_batch_five_atomic_and_duplicate_runner_one_call(engine, setup, monkeypatch, tmp_path):
    from app.tasks.service import Runner
    from app.topics.generation import KIND, VERSION, read, start

    p = configured(engine, setup, monkeypatch)
    calls = []
    handler = handler_for(
        tmp_path, {"topics": [fields(str(i)).model_dump() for i in range(5)]}, calls
    )
    key = str(uuid4())
    with engine.begin() as c:
        value = start(
            c, p, key, GenerateRequest(business_code="motion_comic", mode="batch"), handler
        )
        assert (
            start(c, p, key, GenerateRequest(business_code="motion_comic", mode="batch"), handler)[
                "id"
            ]
            == value["id"]
        )
    assert count_cards(engine, p.org_id) == 0
    runner = Runner(engine, {(KIND, VERSION): handler})
    assert runner.run(p.org_id, value["id"]) == "succeeded"
    runner.run(p.org_id, value["id"])
    assert len(calls) == 1 and count_cards(engine, p.org_id) == 5
    with engine.begin() as c:
        assert len(read(c, p, value["id"])["result"]["topics"]) == 5
        cards = service.listing(c, p, "motion_comic", "candidate", 1)
        assert cards["total"] == "5" and all(x["origin"] == "batch" for x in cards["items"])


def test_brainstorm_explicit_save_once_and_frozen_sparks(engine, setup, monkeypatch, tmp_path):
    from app.tasks.service import Runner
    from app.topics.generation import KIND, VERSION, read, save, start

    p = configured(engine, setup, monkeypatch)
    calls = []
    handler = handler_for(tmp_path, {"topics": [fields().model_dump()]}, calls)
    with engine.begin() as c:
        spark = service.save_spark(c, p, uuid4(), SparkWrite(text="冻结原始闪念"))
        value = start(
            c,
            p,
            str(uuid4()),
            GenerateRequest(
                business_code="motion_comic", mode="brainstorm", spark_ids=[spark["id"]]
            ),
            handler,
        )
        service.save_spark(
            c, p, uuid4(), SparkWrite(id=spark["id"], expected_version=1, text="后续新闪念")
        )
    assert Runner(engine, {(KIND, VERSION): handler}).run(p.org_id, value["id"]) == "succeeded"
    assert len(calls) == 1 and count_cards(engine, p.org_id) == 0
    with engine.begin() as c:
        assert read(c, p, value["id"])["saved_topic_id"] is None
        key = uuid4()
        saved = save(c, p, key, value["id"], GenerationSave(fields=fields()))
        assert saved["source_refs"]["sparks"][0]["text"] == "冻结原始闪念"
        assert saved["source_refs"]["sparks"][0]["version"] == 1
        assert save(c, p, key, value["id"], GenerationSave(fields=fields()))["id"] == saved["id"]
    with engine.begin() as c, pytest.raises(Denied, match="VERSION_CONFLICT"):
        save(c, p, uuid4(), value["id"], GenerationSave(fields=fields()))
    assert count_cards(engine, p.org_id) == 1


def test_invalid_batch_never_publishes_prefix(engine, setup, monkeypatch, tmp_path):
    from app.tasks.service import Runner
    from app.topics.generation import KIND, VERSION, read, start

    p = configured(engine, setup, monkeypatch)
    calls = []
    handler = handler_for(
        tmp_path, {"topics": [fields(str(i)).model_dump() for i in range(4)]}, calls
    )
    with engine.begin() as c:
        value = start(
            c, p, str(uuid4()), GenerateRequest(business_code="motion_comic", mode="batch"), handler
        )
    assert Runner(engine, {(KIND, VERSION): handler}).run(p.org_id, value["id"]) == "failed"
    assert len(calls) == 1 and count_cards(engine, p.org_id) == 0
    with engine.begin() as c:
        value = read(c, p, value["id"])
        assert value["safe_error_code"] == "INVALID_RESPONSE" and value["result"] is None


def test_handoff_authorization_does_not_record_transfer_and_same_key_confirms(engine, setup):
    p = principal(engine, setup)
    t = create(engine, p)
    key = uuid4()
    with engine.begin() as c:
        service.choose(c, p, uuid4(), t["id"], TopicSelect(expected_version=1))
    with engine.begin() as c:
        service.handoff(
            c, p, key, t["id"], TopicHandoff(expected_version=1, method="copy", phase="authorize")
        )
        assert not service.topic(c, p, t["id"])["handed_off"]
    with engine.begin() as c:
        confirmed = service.handoff(
            c, p, key, t["id"], TopicHandoff(expected_version=1, method="copy", phase="confirm")
        )
        assert (
            service.handoff(
                c, p, key, t["id"], TopicHandoff(expected_version=1, method="copy", phase="confirm")
            )
            == confirmed
        )
        assert service.topic(c, p, t["id"])["handed_off"]
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM topic_handoffs WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 1
        )


def test_topic_search_and_handoff_filter_apply_before_paging(engine, setup):
    p = principal(engine, setup)
    for i in range(12):
        create(engine, p, f"前缀{i}")
    t = create(engine, p, "精确目标")
    with engine.begin() as c:
        result = service.listing(c, p, "motion_comic", "candidate", 1, q="精确目标")
        assert result["total"] == "1" and result["items"][0]["id"] == t["id"]
        service.choose(c, p, uuid4(), t["id"], TopicSelect(expected_version=1))
        assert (
            service.listing(c, p, "motion_comic", "production", 1, status="pending")["total"] == "1"
        )
        service.handoff(c, p, uuid4(), t["id"], TopicHandoff(expected_version=1, method="export"))
        assert (
            service.listing(c, p, "motion_comic", "production", 1, status="pending")["total"] == "0"
        )
        assert (
            service.listing(c, p, "motion_comic", "production", 1, status="handed_off")["total"]
            == "1"
        )


def test_handoff_authorization_retry_revalidates_current_revision(engine, setup):
    p = principal(engine, setup)
    t = create(engine, p)
    key = uuid4()
    request = TopicHandoff(expected_version=1, method="copy", phase="authorize")
    with engine.begin() as c:
        service.choose(c, p, uuid4(), t["id"], TopicSelect(expected_version=1))
        service.handoff(c, p, key, t["id"], request)

    # A failed local clipboard write must not turn an old receipt into permission
    # to copy the obsolete revision after another window edits the card.
    with engine.begin() as c:
        service.revise(
            c, p, uuid4(), t["id"], TopicUpdate(expected_version=1, fields=fields("新版本"))
        )
    with engine.begin() as c, pytest.raises(Denied, match="VERSION_CONFLICT"):
        service.handoff(c, p, key, t["id"], request)


def test_truncated_response_keeps_usage_and_request_id_without_cards(
    engine, setup, monkeypatch, tmp_path
):
    from app.model_config import ConfiguredModel
    from app.storage.local import LocalStore
    from app.tasks.service import Runner
    from app.topics.generation import KIND, VERSION, Generate, start

    p = configured(engine, setup, monkeypatch)
    handler = Generate(
        ConfiguredModel(
            lookup=lambda _: ["8.8.8.8"],
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "id": "truncated-call",
                        "usage": {"prompt_tokens": 3064, "completion_tokens": 2047},
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {
                                    "content": "",
                                    "reasoning_content": "private reasoning",
                                },
                            }
                        ],
                    },
                )
            ),
        ),
        LocalStore(tmp_path / "objects"),
    )
    with engine.begin() as c:
        value = start(
            c, p, str(uuid4()), GenerateRequest(business_code="motion_comic", mode="batch"), handler
        )
    assert Runner(engine, {(KIND, VERSION): handler}).run(p.org_id, value["id"]) == "failed"
    assert count_cards(engine, p.org_id) == 0
    with engine.connect() as c:
        e = c.exec_driver_sql(
            "SELECT input_tokens,output_tokens,provider_request_id FROM ai_executions WHERE task_id=%s",
            (value["id"],),
        ).one()
        assert tuple(e) == (3064, 2047, "truncated-call")
