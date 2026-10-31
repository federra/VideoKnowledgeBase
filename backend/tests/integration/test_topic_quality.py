"""Two-call generation in disposable PostgreSQL using HTTP mock transport only."""

import json
from uuid import uuid4

import httpx
import pytest

from app.model_config import ConfiguredModel
from app.storage.local import LocalStore
from app.tasks.service import Runner, TaskError
from app.topics import generation, service
from app.topics.contracts import GenerateRequest, GenerationSave, SparkWrite
from app.topics.generation_v2 import GenerateV2
from tests.integration.test_topics import configured, count_cards, fields

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def begin(engine, p, handler=None):
    with engine.begin() as c:
        spark = service.save_spark(
            c, p, uuid4(), SparkWrite(text="邮差与失语儿童之间互相救助的私有闪念")
        )
        return generation.start(
            c,
            p,
            str(uuid4()),
            GenerateRequest(
                business_code="motion_comic", mode="brainstorm", spark_ids=[spark["id"]]
            ),
            handler,
        )


def fake(tmp_path, outputs, calls):
    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "isolated-quality-" + str(len(calls)),
                "usage": {"prompt_tokens": 21, "completion_tokens": 31},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(outputs[len(calls) - 1], ensure_ascii=False)
                        },
                    }
                ],
            },
        )

    return GenerateV2(
        ConfiguredModel(lookup=lambda _: ["8.8.8.8"], transport=httpx.MockTransport(transport)),
        LocalStore(tmp_path / "objects"),
    )


def test_default_new_task_has_two_calls_one_attempt(engine, setup, monkeypatch):
    p = configured(engine, setup, monkeypatch)
    value = begin(engine, p)
    with engine.connect() as c:
        row = c.exec_driver_sql(
            "SELECT handler_version,max_external_calls,max_attempts FROM tasks WHERE id=%s",
            (value["id"],),
        ).one()
        assert tuple(row) == ("2", 2, 1)


def test_v2_two_executions_abstraction_proof_private_spark_and_explicit_save(
    engine, setup, monkeypatch, tmp_path
):
    p = configured(engine, setup, monkeypatch)
    calls = []
    handler = fake(tmp_path, [{"sources": []}, {"topics": [fields().model_dump()]}], calls)
    monkeypatch.setattr("app.storage.http.get_store", lambda: handler.store)
    value = begin(engine, p, handler)
    runner = Runner(engine, {(generation.KIND, "2"): handler})
    assert runner.run(p.org_id, value["id"]) == "succeeded"
    runner.run(p.org_id, value["id"])
    assert len(calls) == 2 and count_cards(engine, p.org_id) == 0
    assert "邮差与失语儿童" not in json.dumps(calls[0], ensure_ascii=False)
    assert "邮差与失语儿童" in json.dumps(calls[1], ensure_ascii=False)
    with engine.begin() as c:
        assert generation.read(c, p, value["id"])["result"]["topics"][0]["title"] == fields().title
        executions = c.exec_driver_sql(
            "SELECT invocation_no,result_state,input_tokens,output_tokens FROM ai_executions WHERE task_id=%s ORDER BY invocation_no",
            (value["id"],),
        ).all()
        assert [tuple(x) for x in executions] == [
            (1, "completed", 21, 31),
            (2, "completed", 21, 31),
        ]
        proof = c.exec_driver_sql(
            "SELECT a.body_text FROM task_outputs o JOIN raw_assets a ON a.org_id=o.org_id AND a.id=o.raw_asset_id WHERE o.task_id=%s AND o.role='topic_abstraction'",
            (value["id"],),
        ).scalar_one()
        assert json.loads(proof) == {"sources": []}
        saved = generation.save(c, p, uuid4(), value["id"], GenerationSave(fields=fields()))
        assert saved["originality"]["status"] == "no_obvious_overlap"
    assert count_cards(engine, p.org_id) == 1


@pytest.mark.parametrize("bad_stage", [1, 2])
def test_invalid_phase_stops_without_retry_and_keeps_execution_evidence(
    engine, setup, monkeypatch, tmp_path, bad_stage
):
    p = configured(engine, setup, monkeypatch)
    calls = []
    outputs = [{"sources": []}, {"topics": []}]
    if bad_stage == 1:
        outputs[0] = {"sources": [{"source_id": "forged"}]}
    handler = fake(tmp_path, outputs, calls)
    value = begin(engine, p, handler)
    runner = Runner(engine, {(generation.KIND, "2"): handler})
    assert runner.run(p.org_id, value["id"]) == "failed"
    runner.run(p.org_id, value["id"])
    assert len(calls) == bad_stage and count_cards(engine, p.org_id) == 0
    with engine.connect() as c:
        e = c.exec_driver_sql(
            "SELECT result_state,input_tokens,output_tokens,output_file_id FROM ai_executions WHERE task_id=%s ORDER BY invocation_no DESC LIMIT 1",
            (value["id"],),
        ).one()
        assert tuple(e[:3]) == ("failed", 21, 31) and e.output_file_id


def test_no_frozen_material_rejected_before_any_model_call(engine, setup, monkeypatch):
    p = configured(engine, setup, monkeypatch)
    with engine.begin() as c, pytest.raises(TaskError, match="INSUFFICIENT_MATERIAL"):
        generation.start(
            c, p, str(uuid4()), GenerateRequest(business_code="motion_comic", mode="batch")
        )
