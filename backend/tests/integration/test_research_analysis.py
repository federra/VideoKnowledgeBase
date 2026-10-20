"""S07.3 disposable PostgreSQL tests; no paid model or platform calls."""

from uuid import uuid4

import pytest

from tests.integration.test_research_intake import principal, request

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def prepared(engine, setup):
    from app.contracts.models import InputSetCreate
    from app.research.inputs import create_input
    from app.research.service import direct_intake

    p = principal(engine, setup)
    with engine.begin() as c:
        material = direct_intake(c, p, uuid4(), request())
        payload = InputSetCreate(
            work_id=material["work_id"],
            scope="artifact",
            artifact_id=material["artifact_id"],
            items=[
                {
                    "artifact_version_id": material["artifact_version_id"],
                    "role": "primary",
                    "position": 0,
                }
            ],
        )
        frozen = create_input(c, p, uuid4(), payload)
    return p, material, frozen, payload


def test_input_set_seals_exact_versions_and_replays(engine, setup):
    from app.research.inputs import create_input, read_input

    p, material, frozen, req = prepared(engine, setup)
    with engine.begin() as c:
        again = create_input(c, p, uuid4(), req)
        assert again["id"] == frozen["id"]
        read = read_input(c, p, frozen["id"])
        assert read["items"][0]["artifact_version_id"] == material["artifact_version_id"]
        assert read["sealed_at"] is not None
        assert read["normalization_version"] == 1
        assert read["total_episode_count_at_input"] == 5
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM analysis_runs WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )


def test_input_rejects_foreign_versions_and_conflicting_scope(engine, setup):
    from app.research.inputs import create_input
    from app.security.errors import Denied

    p, _, _, req = prepared(engine, setup)
    with pytest.raises(Denied), engine.begin() as c:
        create_input(c, p, uuid4(), req.model_copy(update={"work_id": setup[4]}))
    with pytest.raises(Denied), engine.begin() as c:
        create_input(c, p, uuid4(), req.model_copy(update={"artifact_id": uuid4()}))


def test_prediction_draft_freeze_confirm_retract_and_context(engine, setup):
    from app.collection.service import insert
    from app.research.prediction_contracts import DraftCreate
    from app.research.predictions import (
        confirm_prediction,
        create_draft,
        freeze_prediction,
        read_prediction,
        retract_prediction,
    )
    from app.security.errors import Denied
    from tests.integration.test_security import grant

    p, _, frozen, _ = prepared(engine, setup)
    with engine.begin() as c:
        grant(
            c,
            p.org_id,
            p.member_id,
            p.member_id,
            ["prediction.freeze", "prediction.edit", "prediction.retract"],
        )
        metric = insert(
            c,
            "metric_specs",
            p.org_id,
            code="fixture.play",
            version_no=1,
            name="合成测试播放",
            unit="次",
            definition="仅隔离测试，发布后24小时累计",
            aggregation_kind="cumulative",
        )
        request = DraftCreate(
            input_set_id=frozen["id"],
            metric_spec_id=metric,
            platform_code="douyin",
            window_start_offset_seconds="0",
            window_end_offset_seconds="86400",
            conditions={"account": "unknown", "distribution": "unknown"},
            reliability="estimable",
            lower_bound="10",
            upper_bound="20",
            rationale="隔离人工判断",
            uncertainty_note="仅测试冻结，不代表真实预测",
        )
        draft = create_draft(c, p, uuid4(), request)
        result = freeze_prediction(c, p, uuid4(), draft["id"], draft["lock_version"])
        assert result["confirmed_at"] is None
    with engine.begin() as c:
        confirm_prediction(c, p, result["id"])
        got = read_prediction(c, p, result["id"])
        assert got["confirmed_at"] >= got["frozen_at"]
        assert got["context_kind"] == "unknown" and got["outcome_exposure"] == "unknown"
        again = freeze_prediction(c, p, uuid4(), draft["id"], draft["lock_version"])
        assert again["id"] == got["id"]
        retract_prediction(c, p, uuid4(), got["id"], "隔离撤销")
        assert read_prediction(c, p, got["id"])["retracted_at"] is not None
    insufficient = request.model_copy(
        update={"reliability": "insufficient_evidence", "lower_bound": None, "upper_bound": None}
    )
    with engine.begin() as c:
        bad = create_draft(c, p, uuid4(), insufficient)
    with pytest.raises(Denied, match="INSUFFICIENT_MATERIAL"), engine.begin() as c:
        freeze_prediction(c, p, uuid4(), bad["id"], bad["lock_version"])


def analysis_ready(engine, p):
    from app.collection.service import insert
    from app.research.analysis import parameters
    from app.research.stage_model import output_schema
    from app.security.primitives import digest
    from tests.integration.test_schema import approve_standard, standard
    from tests.integration.test_security import grant

    with engine.begin() as c:
        grant(c, p.org_id, p.member_id, p.member_id, ["research.run", "standard.read"])
        for kind in ("analysis_template", "rubric"):
            sid, rev = standard(c, p.org_id, p.member_id, kind=kind)
            approve_standard(c, p.org_id, p.member_id, rev)
            c.exec_driver_sql(
                "UPDATE standards SET active_revision_id=%s,lock_version=lock_version+1 WHERE id=%s",
                (rev, sid),
            )
        connection = insert(
            c,
            "provider_connections",
            p.org_id,
            provider_code="deepseek",
            name="isolated",
            secret_ref="DEEPSEEK_KEY",
            enabled=True,
        )
        for purpose in ("decompose", "evaluate", "predict"):
            definition = {
                "model": "deepseek-flash",
                "parameters": parameters(purpose),
                "schema": output_schema(purpose),
            }
            insert(
                c,
                "ai_config_revisions",
                p.org_id,
                config_key="research." + purpose + ".v2",
                version_no=1,
                task_kind="research." + purpose,
                provider_connection_id=connection,
                model_identifier="deepseek-flash",
                parameters=definition["parameters"],
                output_schema=definition["schema"],
                content_sha256=digest(definition),
                created_by=p.member_id,
            )


def test_analysis_budget_independent_inputs_and_cited_report(engine, setup, tmp_path):
    import json

    import httpx
    from pydantic import SecretStr

    from app.research.analysis import read_report, start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.research.analysis_task import Analyze
    from app.research.stage_model import StageModel
    from app.storage.local import LocalStore
    from app.tasks.service import Runner

    p, material, frozen, _ = prepared(engine, setup)
    analysis_ready(engine, p)
    calls = []

    def transport(req):
        sent = json.loads(req.content)
        calls.append(sent)
        text = json.loads(sent["messages"][1]["content"])["segments"][0]["text"]
        return httpx.Response(
            200,
            json={
                "id": "isolated-response",
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "result_state": "completed",
                                    "coverage": "partial",
                                    "limitations": ["仅当前材料，未验收视频"],
                                    "claims": [
                                        {
                                            "key": "goal",
                                            "dimension": "人物设计",
                                            "finding": "主角发现线索",
                                            "evidence": [{"segment_id": "s1", "quote": text}],
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ],
            },
        )

    store = LocalStore(tmp_path / "objects")
    handler = Analyze(
        "decompose",
        StageModel(key=lambda: SecretStr("fixture"), transport=httpx.MockTransport(transport)),
        store,
    )
    try:
        with engine.begin() as c:
            result = start_analysis(
                c,
                p,
                uuid4(),
                AnalysisRequest(
                    input_set_id=frozen["id"],
                    purpose="decompose",
                    execute_now=True,
                    max_external_calls=1,
                ),
                handler,
            )
        assert (
            Runner(engine, {("research.decompose", "2"): handler}).run(p.org_id, result["id"])
            == "succeeded"
        )
        with engine.begin() as c:
            rid = c.exec_driver_sql(
                "SELECT report_id FROM task_outputs WHERE task_id=%s AND report_id IS NOT NULL",
                (result["id"],),
            ).scalar_one()
            report = read_report(c, p, rid)
            assert report["coverage_kind"] == "partial"
            assert report["body"]["claims"][0]["finding"] == "主角发现线索"
            assert len(report["evidence"]) == 1
            assert (
                c.exec_driver_sql(
                    "SELECT latest_report_id FROM works WHERE id=%s", (material["work_id"],)
                ).scalar_one()
                == rid
            )
        assert len(calls) == 1
        manifest = calls[0]["messages"][1]["content"]
        assert (
            "quality_grade" not in manifest
            and "additional_learning" not in manifest
            and "learning_tags" not in manifest
        )
    finally:
        store.close()


def test_analysis_does_not_grant_execution_or_invent_approved_standards(engine, setup):
    from app.research.analysis import start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.security.errors import Denied

    p, _, frozen, _ = prepared(engine, setup)
    with pytest.raises(Denied), engine.begin() as c:
        start_analysis(
            c,
            p,
            uuid4(),
            AnalysisRequest(
                input_set_id=frozen["id"],
                purpose="decompose",
                execute_now=True,
                max_external_calls=1,
            ),
        )
    analysis_ready(engine, p)
    with pytest.raises(Denied, match="BUDGET_EXHAUSTED"), engine.begin() as c:
        start_analysis(
            c,
            p,
            uuid4(),
            AnalysisRequest(
                input_set_id=frozen["id"],
                purpose="decompose",
                execute_now=True,
                max_external_calls=0,
            ),
        )


def test_research_http_input_history_and_unapproved_execution(engine, setup, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.http import get_engine
    from app.security.sessions import csrf_for

    _p, material, frozen, payload = prepared(engine, setup)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://localhost:8000")
        client.cookies.set("cip_session", setup[2], path="/api/v1")
        headers = {
            "Origin": "http://localhost:5173",
            "X-CSRF-Token": csrf_for(setup[2]),
            "Idempotency-Key": str(uuid4()),
        }
        created = client.post(
            "/api/v1/input-sets", json=payload.model_dump(mode="json"), headers=headers
        )
        assert created.status_code == 201, created.text
        assert created.json()["data"]["id"] == str(frozen["id"])
        assert client.get("/api/v1/input-sets/" + str(frozen["id"])).status_code == 200
        history = client.get("/api/v1/works/" + str(material["work_id"]) + "/analysis-history")
        assert history.status_code == 200, history.text
        assert history.json()["data"]["reports"] == []
        rejected = client.post(
            "/api/v1/analysis-runs",
            json={"input_set_id": str(frozen["id"]), "execute_now": True, "max_external_calls": 1},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        assert rejected.status_code in (403, 404), rejected.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("purpose", ["evaluate", "predict"])
def test_evaluation_and_prediction_are_separate_and_keep_insufficiency(
    engine, setup, tmp_path, purpose
):
    import json

    import httpx
    from pydantic import SecretStr

    from app.research.analysis import history, start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.research.analysis_task import Analyze
    from app.research.stage_model import StageModel
    from app.storage.local import LocalStore
    from app.tasks.service import Runner

    p, material, frozen, _ = prepared(engine, setup)
    analysis_ready(engine, p)
    output = {
        "result_state": "insufficient_evidence",
        "coverage": "partial",
        "limitations": ["隔离材料不足"],
        "claims": [],
    }
    output.update(
        {"grade": None, "dimensions": []}
        if purpose == "evaluate"
        else {
            "metric_code": None,
            "window_seconds": None,
            "lower_bound": None,
            "upper_bound": None,
            "uncertainty_note": "缺少校准与发布条件",
        }
    )
    calls = []

    def transport(req):
        calls.append(req)
        return httpx.Response(
            200,
            json={
                "id": "isolated",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(output, ensure_ascii=False)},
                    }
                ],
            },
        )

    store = LocalStore(tmp_path / "files")
    handler = Analyze(
        purpose,
        StageModel(key=lambda: SecretStr("test"), transport=httpx.MockTransport(transport)),
        store,
    )
    try:
        with engine.begin() as c:
            task = start_analysis(
                c,
                p,
                uuid4(),
                AnalysisRequest(
                    input_set_id=frozen["id"],
                    purpose=purpose,
                    execute_now=True,
                    max_external_calls=1,
                ),
                handler,
            )
        assert (
            Runner(engine, {("research." + purpose, "2"): handler}).run(p.org_id, task["id"])
            == "succeeded"
        )
        with engine.begin() as c:
            got = history(c, p, material["work_id"])
            assert got["reports"] == [] and got["frozen_predictions"] == []
            assert (
                c.exec_driver_sql(
                    "SELECT business_outcome FROM tasks WHERE id=%s", (task["id"],)
                ).scalar_one()
                == "insufficient_evidence"
            )
            if purpose == "evaluate":
                assert got["evaluations"][0]["quality_grade"] is None
            else:
                assert got["prediction_assessments"][0]["result_state"] == "insufficient_evidence"
        assert len(calls) == 1
    finally:
        store.close()


def test_late_report_cannot_replace_newer_generation(engine, setup, tmp_path):
    import json

    import httpx
    from pydantic import SecretStr

    from app.research.analysis import start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.research.analysis_task import Analyze
    from app.research.stage_model import StageModel
    from app.storage.local import LocalStore
    from app.tasks.service import Runner

    p, material, frozen, _ = prepared(engine, setup)
    analysis_ready(engine, p)

    def transport(req):
        segment = json.loads(json.loads(req.content)["messages"][1]["content"])["segments"][0]
        output = {
            "result_state": "completed",
            "coverage": "partial",
            "limitations": ["仅测试局部材料"],
            "claims": [
                {
                    "key": "goal",
                    "dimension": "人物设计",
                    "finding": "发现线索",
                    "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}],
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "id": "isolated",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(output, ensure_ascii=False)},
                    }
                ],
            },
        )

    store = LocalStore(tmp_path / "files")
    handler = Analyze(
        "decompose",
        StageModel(key=lambda: SecretStr("test"), transport=httpx.MockTransport(transport)),
        store,
    )
    runner = Runner(engine, {("research.decompose", "2"): handler})
    req = AnalysisRequest(input_set_id=frozen["id"], execute_now=True, max_external_calls=1)
    try:
        with engine.begin() as c:
            old = start_analysis(c, p, uuid4(), req, handler)
        ticket = runner.claim(p.org_id, old["id"])
        assert ticket
        with engine.begin() as c:
            new = start_analysis(c, p, uuid4(), req, handler)
        assert runner.run(p.org_id, new["id"]) == "succeeded"
        result = handler.execute_ticket(runner, ticket, lambda: None)
        assert runner.complete(ticket, result) == "succeeded"
        with engine.begin() as c:
            current = c.exec_driver_sql(
                "SELECT latest_report_id FROM works WHERE id=%s", (material["work_id"],)
            ).scalar_one()
            owner = c.exec_driver_sql(
                "SELECT r.task_id FROM analysis_reports p JOIN analysis_runs r ON r.id=p.analysis_run_id WHERE p.id=%s",
                (current,),
            ).scalar_one()
            assert owner == new["id"]
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM analysis_reports WHERE work_id=%s", (material["work_id"],)
                ).scalar_one()
                == 2
            )
    finally:
        store.close()


def test_invalid_model_quote_fails_without_report_or_retry(engine, setup, tmp_path):
    import json

    import httpx
    from pydantic import SecretStr

    from app.research.analysis import start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.research.analysis_task import Analyze
    from app.research.stage_model import StageModel
    from app.storage.local import LocalStore
    from app.tasks.service import Runner

    p, _, frozen, _ = prepared(engine, setup)
    analysis_ready(engine, p)
    calls = []

    def transport(req):
        calls.append(req)
        output = {
            "result_state": "completed",
            "coverage": "partial",
            "limitations": ["隔离测试"],
            "claims": [
                {
                    "key": "bad",
                    "dimension": "人物设计",
                    "finding": "无依据",
                    "evidence": [{"segment_id": "s1", "quote": "原文不存在的证据"}],
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "id": "isolated",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
            },
        )

    store = LocalStore(tmp_path / "files")
    handler = Analyze(
        "decompose",
        StageModel(key=lambda: SecretStr("test"), transport=httpx.MockTransport(transport)),
        store,
    )
    try:
        with engine.begin() as c:
            task = start_analysis(
                c,
                p,
                uuid4(),
                AnalysisRequest(input_set_id=frozen["id"], execute_now=True, max_external_calls=1),
                handler,
            )
        runner = Runner(engine, {("research.decompose", "2"): handler})
        assert runner.run(p.org_id, task["id"]) == "failed"
        assert runner.run(p.org_id, task["id"]) == "failed"
        assert len(calls) == 1
        with engine.connect() as c:
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM analysis_reports WHERE org_id=%s", (p.org_id,)
                ).scalar_one()
                == 0
            )
            assert (
                c.exec_driver_sql(
                    "SELECT result_state FROM ai_executions WHERE task_id=%s", (task["id"],)
                ).scalar_one()
                == "failed"
            )
    finally:
        store.close()


def test_report_counts_only_units_supported_by_cited_primary_material(engine, setup, tmp_path):
    import json

    import httpx
    from pydantic import SecretStr

    from app.contracts.models import InputSetCreate
    from app.research.analysis import start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.research.analysis_task import Analyze
    from app.research.contracts import MaterialIntake
    from app.research.inputs import create_input
    from app.research.service import add_material
    from app.research.stage_model import StageModel
    from app.storage.local import LocalStore
    from app.tasks.service import Runner

    p, material, _, _ = prepared(engine, setup)
    analysis_ready(engine, p)
    with engine.begin() as c:
        extra = add_material(
            c,
            p,
            uuid4(),
            material["work_id"],
            MaterialIntake(
                title="第三集",
                material_kind="script",
                origin="text",
                body_text="第三集另一段正文。",
                episode_no=3,
            ),
        )
        frozen = create_input(
            c,
            p,
            uuid4(),
            InputSetCreate(
                work_id=material["work_id"],
                scope="work",
                items=[
                    {
                        "artifact_version_id": material["artifact_version_id"],
                        "role": "primary",
                        "position": 0,
                    },
                    {
                        "artifact_version_id": extra["artifact_version_id"],
                        "role": "primary",
                        "position": 1,
                    },
                ],
            ),
        )

    def transport(req):
        segment = json.loads(json.loads(req.content)["messages"][1]["content"])["segments"][0]
        output = {
            "result_state": "completed",
            "coverage": "partial",
            "limitations": ["只支持第2集当前材料"],
            "claims": [
                {
                    "key": "goal",
                    "dimension": "人物设计",
                    "finding": "发现线索",
                    "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}],
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "id": "isolated",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(output, ensure_ascii=False)},
                    }
                ],
            },
        )

    store = LocalStore(tmp_path / "files")
    handler = Analyze(
        "decompose",
        StageModel(key=lambda: SecretStr("fixture"), transport=httpx.MockTransport(transport)),
        store,
    )
    try:
        with engine.begin() as c:
            task = start_analysis(
                c,
                p,
                uuid4(),
                AnalysisRequest(input_set_id=frozen["id"], execute_now=True, max_external_calls=1),
                handler,
            )
        assert (
            Runner(engine, {("research.decompose", "2"): handler}).run(p.org_id, task["id"])
            == "succeeded"
        )
        with engine.connect() as c:
            states = dict(
                c.exec_driver_sql(
                    "SELECT episode_no_at_report,coverage_state FROM report_units WHERE org_id=%s",
                    (p.org_id,),
                ).all()
            )
            assert states == {2: "analyzed", 3: "insufficient_evidence"}
    finally:
        store.close()


def test_uploaded_text_report_resolves_parent_version_and_original_line(engine, setup, tmp_path):
    import json

    import httpx
    from pydantic import SecretStr

    from app.contracts.models import FileUploadQuery, InputSetCreate
    from app.processing.research import Parse
    from app.research.analysis import read_report, start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.research.analysis_task import Analyze
    from app.research.contracts import MaterialIntake
    from app.research.inputs import create_input
    from app.research.service import add_material
    from app.research.stage_model import StageModel
    from app.storage.local import LocalStore
    from app.storage.service import save
    from app.tasks.service import Runner

    p, material, _, _ = prepared(engine, setup)
    analysis_ready(engine, p)
    store = LocalStore(tmp_path / "files")
    try:
        with store.stage() as staged:
            staged.write("上传第一行。\n\n上传第三行。".encode())
            f = save(
                engine,
                store,
                setup[2],
                uuid4(),
                FileUploadQuery(
                    work_id=material["work_id"],
                    expected_work_lock_version="1",
                    original_name="authorized.txt",
                    media_type="text/plain",
                ),
                staged,
            )
        with engine.begin() as c:
            uploaded = add_material(
                c,
                p,
                uuid4(),
                material["work_id"],
                MaterialIntake(
                    title="上传文本",
                    origin="upload",
                    file_id=f["id"],
                    material_kind="script",
                    episode_no=3,
                ),
            )
        assert (
            Runner(engine, {("research.parse", "1"): Parse(store)}).run(
                p.org_id, uploaded["task_id"]
            )
            == "succeeded"
        )
        with engine.begin() as c:
            frozen = create_input(
                c,
                p,
                uuid4(),
                InputSetCreate(
                    work_id=material["work_id"],
                    scope="artifact",
                    artifact_id=uploaded["artifact_id"],
                    items=[
                        {
                            "artifact_version_id": uploaded["artifact_version_id"],
                            "role": "primary",
                            "position": 0,
                        }
                    ],
                ),
            )

        def transport(req):
            segment = json.loads(json.loads(req.content)["messages"][1]["content"])["segments"][1]
            output = {
                "result_state": "completed",
                "coverage": "partial",
                "limitations": ["仅上传文本"],
                "claims": [
                    {
                        "key": "p",
                        "dimension": "人物设计",
                        "finding": "来自第三行的局部结论",
                        "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}],
                    }
                ],
            }
            return httpx.Response(
                200,
                json={
                    "id": "isolated",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(output, ensure_ascii=False)},
                        }
                    ],
                },
            )

        handler = Analyze(
            "decompose",
            StageModel(key=lambda: SecretStr("fixture"), transport=httpx.MockTransport(transport)),
            store,
        )
        with engine.begin() as c:
            task = start_analysis(
                c,
                p,
                uuid4(),
                AnalysisRequest(input_set_id=frozen["id"], execute_now=True, max_external_calls=1),
                handler,
            )
        assert (
            Runner(engine, {("research.decompose", "2"): handler}).run(p.org_id, task["id"])
            == "succeeded"
        )
        with engine.begin() as c:
            rid = c.exec_driver_sql(
                "SELECT report_id FROM task_outputs WHERE task_id=%s AND report_id IS NOT NULL",
                (task["id"],),
            ).scalar_one()
            ref = read_report(c, p, rid)["evidence"][0]
            assert ref["raw_asset_id"] is not None and ref["artifact_version_id"] is None
            assert ref["target_artifact_version_id"] == uploaded["artifact_version_id"]
            assert ref["target_episode_no"] == 3 and ref["paragraph_no"] == 3
        # Parsed text from another version cannot be smuggled into a frozen input.
        with pytest.raises(Exception, match="parsed source"), engine.begin() as c:
            from app.collection.service import insert
            from app.core.models import metadata

            invalid = insert(
                c,
                "input_sets",
                p.org_id,
                work_id=material["work_id"],
                scope="artifact",
                artifact_id=material["artifact_id"],
                business_code="motion_comic",
                manifest_sha256="f" * 64,
                parsed_sources={
                    str(material["artifact_version_id"]): {
                        "raw_asset_id": str(ref["raw_asset_id"]),
                        "sha256": c.exec_driver_sql(
                            "SELECT sha256 FROM raw_assets WHERE id=%s", (ref["raw_asset_id"],)
                        ).scalar_one(),
                    }
                },
            )
            c.execute(
                metadata.tables["input_set_items"]
                .insert()
                .values(
                    org_id=p.org_id,
                    input_set_id=invalid,
                    work_id=material["work_id"],
                    artifact_version_id=material["artifact_version_id"],
                    role="primary",
                    position=0,
                )
            )
            c.exec_driver_sql("SELECT cip_seal('input_sets',%s,%s)", (p.org_id, invalid))

    finally:
        store.close()
