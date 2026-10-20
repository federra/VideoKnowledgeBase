"""S07.4 disposable PostgreSQL; no project data or paid requests."""

from uuid import UUID, uuid4

import pytest

from tests.integration.test_research_intake import principal
from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def editor(engine, setup):
    p = principal(engine, setup)
    with engine.begin() as c:
        grant(
            c,
            p.org_id,
            p.member_id,
            p.member_id,
            [
                "knowledge.edit",
                "knowledge.candidate.read",
                "knowledge.review",
                "knowledge.review.run",
                "knowledge.publish",
                "evaluation.review",
                "report.review",
                "report.review.run",
                "standard.approve",
                "standard.read",
            ],
        )
    return p


def candidate(**changes):
    from app.contracts.models import KnowledgeCreate

    return KnowledgeCreate(
        title="合成测试知识",
        body_text="角色发现线索后改变行动；仅为案例观察。",
        knowledge_type="case_experience",
        browse_category="dna_case",
        business_codes=["motion_comic"],
        tags=[{"kind": "stage", "code": "script"}],
        limitations="隔离样本，不能推广。",
        **changes,
    )


def test_candidate_is_not_formal_and_revision_requires_new_review(engine, setup):
    from app.contracts.models import HumanDecisionCreate, KnowledgeRevisionCreate, ReviewCreate
    from app.knowledge.reviews import human_decision, read_review, request_review
    from app.knowledge.service import create, listing, published, read_candidate, revise
    from app.security.errors import Denied

    p = editor(engine, setup)
    key = uuid4()
    with engine.begin() as c:
        first = create(c, p, key, candidate())
        assert first["state"] == "pending_ai"
        assert create(c, p, key, candidate())["id"] == first["id"]
        rv = read_candidate(c, p, UUID(str(first["revision_id"])))
        rr = request_review(
            c, p, uuid4(), ReviewCreate(purpose="knowledge_release", target_id=rv["id"])
        )
        assert read_review(c, p, UUID(str(rr["id"])))["ai_head_id"] is None
        assert listing(c, p, "motion_comic")["items"] == []
    with pytest.raises(Denied), engine.begin() as c:
        published(c, p, UUID(str(first["id"])))
    with pytest.raises(Denied, match="REVIEW_STALE"), engine.begin() as c:
        human_decision(
            c,
            p,
            uuid4(),
            UUID(str(rr["id"])),
            HumanDecisionCreate(
                expected_head_id=None,
                expected_head_lock_version=None,
                reviewed_ai_decision_id=None,
                verdict="approved",
                reason="不能跳审",
            ),
        )
    with engine.begin() as c:
        req = KnowledgeRevisionCreate(
            **candidate().model_dump(),
            expected_lock_version=first["lock_version"],
            revision_reason="补充限制",
        )
        v2 = revise(c, p, uuid4(), UUID(str(first["id"])), req)
        assert v2["version_no"] == 2
        assert v2["id"] != rv["id"]
        assert read_review(c, p, UUID(str(rr["id"])))["target_id"] == rv["id"]
    with pytest.raises(Exception, match="VERSION_CONFLICT"), engine.begin() as c:
        revise(c, p, uuid4(), UUID(str(first["id"])), req)


def test_candidate_replay_and_queue_current_authorization(engine, setup):
    from app.knowledge.service import create, listing
    from app.security.errors import Denied

    p = editor(engine, setup)
    key = uuid4()
    with engine.begin() as c:
        create(c, p, key, candidate())
        assert len(listing(c, p, "motion_comic", candidate=True)["items"]) == 1
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s",
            (p.org_id, p.member_id),
        )
    with pytest.raises(Denied), engine.begin() as c:
        create(c, p, key, candidate())
    with engine.begin() as c:
        assert listing(c, p, "motion_comic", candidate=True)["items"] == []


def install_ai(c, p, rr, *, verdict="approved"):
    from app.knowledge.reviews import access, append_decision, heads
    from app.research.service import direct_intake
    from tests.integration.test_research_intake import request
    from tests.integration.test_schema import ai_task

    m = direct_intake(c, p, uuid4(), request())
    ex, _ = ai_task(c, p.org_id, p.member_id, m["work_id"], request=rr)
    r, _ = access(c, p, rr)
    old = heads(c, p, rr).get("ai", {})
    return append_decision(
        c,
        p,
        r,
        "ai",
        verdict,
        "合成AI结果",
        execution=ex,
        expected_id=old.get("decision_id"),
        expected_version=old.get("lock_version"),
    )


def test_knowledge_publication_cas_head_and_formal_revision_isolation(engine, setup):
    from app.contracts.models import HumanDecisionCreate, KnowledgeRevisionCreate, PublishCreate
    from app.knowledge.reviews import human_decision, publish, read_review
    from app.knowledge.service import create, listing, published, revise, revision_request
    from app.security.errors import Denied

    p = editor(engine, setup)
    with engine.begin() as c:
        first = create(c, p, uuid4(), candidate())
        kid = first["id"]
        rid = first["revision_id"]
        rr = revision_request(c, p, rid)
        aid = install_ai(c, p, rr)
        h = human_decision(
            c,
            p,
            uuid4(),
            rr,
            HumanDecisionCreate(
                expected_head_id=None,
                expected_head_lock_version=None,
                reviewed_ai_decision_id=aid,
                verdict="approved",
                reason="独立人工核对",
            ),
        )
        old = read_review(c, p, rr)
        assert len(old["decisions"]) == 2
        pubreq = PublishCreate(
            expected_lock_version=first["lock_version"],
            revision_id=rid,
            review_request_id=rr,
            ai_decision_id=aid,
            human_decision_id=h["id"],
        )
    # A second AI decision makes the old human approval stale, even on same text.
    with engine.begin() as c:
        aid2 = install_ai(c, p, rr)
    with pytest.raises(Denied, match="REVIEW_STALE"), engine.begin() as c:
        publish(c, p, uuid4(), kid, pubreq)
    with engine.begin() as c:
        now = read_review(c, p, rr)
        h2 = human_decision(
            c,
            p,
            uuid4(),
            rr,
            HumanDecisionCreate(
                expected_head_id=h["id"],
                expected_head_lock_version=now["human_head_lock_version"],
                reviewed_ai_decision_id=aid2,
                verdict="approved",
                reason="复核新AI决定",
            ),
        )
        req = pubreq.model_copy(update={"ai_decision_id": aid2, "human_decision_id": h2["id"]})
        key = uuid4()
        pub = publish(c, p, key, kid, req)
        assert publish(c, p, key, kid, req)["id"] == pub["id"]
        assert len(listing(c, p, "motion_comic")["items"]) == 1
        formal = published(c, p, kid)
        second = candidate().model_dump()
        second.update(title="第二版候选", business_codes=["story_short"])
        v2 = revise(
            c,
            p,
            uuid4(),
            kid,
            KnowledgeRevisionCreate(
                **second,
                expected_lock_version=formal["lock_version"],
                revision_reason="业务调整需重审",
            ),
        )
        assert v2["version_no"] == 2
        assert published(c, p, kid)["revision"]["id"] == rid
        assert listing(c, p, "story_short")["items"] == []
        assert listing(c, p, "motion_comic")["items"][0]["title"] == "合成测试知识"
        assert len(listing(c, p, "story_short", candidate=True)["items"]) == 1
    with pytest.raises(Denied, match="REVIEW_STALE"), engine.begin() as c:
        install_ai(c, p, rr)


@pytest.mark.parametrize("case", ["success", "stale", "invalid_quote", "insufficient", "manual"])
def test_review_worker_freezes_comparison_and_publishes_only_current_head(
    engine, setup, tmp_path, case, monkeypatch
):
    import json

    import httpx
    from pydantic import SecretStr

    from app.collection.service import insert
    from app.contracts.models import ReviewCreate
    from app.knowledge.contracts import ApprovePublish
    from app.knowledge.model import KnowledgeModel, output_schema, parameters
    from app.knowledge.reviews import approve_publish, read_review, request_review
    from app.knowledge.service import create, listing, revision_request
    from app.knowledge.tasks import KnowledgeTask
    from app.processing.research import Parse
    from app.research.service import direct_intake
    from app.security.primitives import digest
    from app.storage.local import LocalStore
    from app.tasks.service import Runner
    from tests.integration.test_research_intake import request
    from tests.integration.test_schema import approve_standard, standard

    p = editor(engine, setup)
    with engine.begin() as c:
        material = direct_intake(c, p, uuid4(), request())
    assert (
        Runner(engine, {("research.parse", "1"): Parse()}).run(p.org_id, material["task_id"])
        == "succeeded"
    )
    with engine.begin() as c:
        eid = c.exec_driver_sql(
            "SELECT e.id FROM evidence_refs e JOIN raw_assets r ON r.org_id=e.org_id AND r.id=e.raw_asset_id WHERE e.org_id=%s AND r.parent_artifact_version_id=%s LIMIT 1",
            (p.org_id, material["artifact_version_id"]),
        ).scalar_one()
        if case == "manual":
            from app.knowledge.contracts import KnowledgeWrite

            req = KnowledgeWrite(
                **candidate().model_dump(),
                manual_source={
                    "body_text": "主角发现线索后，转身调查门外动静。",
                    "attribution": "人工提供的授权片段",
                },
            )
        else:
            req = candidate(evidence_ids=[eid])
        x = create(c, p, uuid4(), req)
        rr = revision_request(c, p, x["revision_id"])
        _sid, rev = standard(c, p.org_id, p.member_id, kind="prompt")
        approve_standard(c, p.org_id, p.member_id, rev)
        conn = insert(
            c,
            "provider_connections",
            p.org_id,
            provider_code="deepseek",
            name="knowledge-isolated",
            secret_ref="DEEPSEEK_KEY",
            enabled=True,
        )
        definition = {
            "model": "deepseek-flash",
            "parameters": parameters("review"),
            "schema": output_schema("review"),
        }
        insert(
            c,
            "ai_config_revisions",
            p.org_id,
            config_key="knowledge.review.v2",
            version_no=1,
            task_kind="knowledge.review",
            provider_connection_id=conn,
            model_identifier="deepseek-flash",
            prompt_revision_id=rev,
            parameters=definition["parameters"],
            output_schema=definition["schema"],
            content_sha256=digest(definition),
            created_by=p.member_id,
        )
        result = request_review(
            c,
            p,
            uuid4(),
            ReviewCreate(
                purpose="knowledge_release",
                target_id=x["revision_id"],
                execute_ai=True,
                max_external_calls=1,
            ),
        )
        tid = UUID(str(result["task"]["id"]))
    calls = []

    def transport(req):
        value = json.loads(json.loads(req.content)["messages"][1]["content"])
        calls.append(value)
        segment = value["segments"][0]
        body = {
            "result_state": "completed",
            "coverage": "partial",
            "limitations": ["仅授权业务范围"],
            "claims": [
                {
                    "key": "e",
                    "dimension": "来源支持",
                    "finding": "引用对应当前材料",
                    "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}],
                }
            ],
            "decision": "approved",
            "checks": [
                {"kind": k, "state": "supported", "reason": "核对冻结输入", "claim_keys": ["e"]}
                for k in ["support", "completeness", "duplicate", "conflict", "applicability"]
            ],
        }
        if case == "stale":
            from app.contracts.models import KnowledgeRevisionCreate
            from app.knowledge.service import revise

            with engine.begin() as c:
                revise(
                    c,
                    p,
                    uuid4(),
                    x["id"],
                    KnowledgeRevisionCreate(
                        **candidate(evidence_ids=[eid]).model_dump(),
                        expected_lock_version=x["lock_version"],
                        revision_reason="调用中修订",
                    ),
                )
        if case == "invalid_quote":
            body["claims"][0]["evidence"][0]["quote"] = "不存在的引文"
        if case == "insufficient":
            body.update(result_state="insufficient_evidence", decision="insufficient_evidence")
            for check in body["checks"]:
                check["state"] = "insufficient_evidence"
        return httpx.Response(
            200,
            json={
                "id": "isolate",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(body, ensure_ascii=False)},
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 7},
            },
        )

    task = KnowledgeTask(
        "review",
        model=KnowledgeModel(
            lambda: SecretStr("isolated"), transport=httpx.MockTransport(transport)
        ),
        store=LocalStore(tmp_path),
    )
    if case == "success":
        from app.knowledge import worker as isolated
        from app.tasks import worker as general

        routed = []
        monkeypatch.setattr(
            general, "runtime", lambda: Runner(engine, {("knowledge.review", "2"): task})
        )
        monkeypatch.setattr(
            isolated, "dispatch_knowledge", lambda org, identity: routed.append((org, identity))
        )
        general.execute(str(p.org_id), str(tid))
        assert routed == [(p.org_id, tid)]
        assert calls == []
    result = Runner(engine, {("knowledge.review", "2"): task}).run(p.org_id, tid)
    with engine.begin() as c:
        error = c.exec_driver_sql(
            "SELECT safe_error_code FROM tasks WHERE org_id=%s AND id=%s", (p.org_id, tid)
        ).scalar_one()
    assert result == ("failed" if case in ("stale", "invalid_quote") else "succeeded"), error
    if case not in ("success", "manual"):
        with engine.begin() as c:
            assert read_review(c, p, rr)["ai_head_id"] is None
            assert listing(c, p, "motion_comic")["items"] == []
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM ai_executions WHERE org_id=%s AND task_id=%s",
                    (p.org_id, tid),
                ).scalar_one()
                == 1
            )
        assert len(calls) == 1
        return
    assert (
        len(calls) == 1
        and calls[0]["comparisons"] == []
        and calls[0]["comparison_complete"] is True
    )
    if case == "manual":
        assert calls[0]["segments"][0]["text"] == "主角发现线索后，转身调查门外动静。"
        assert calls[0]["source_provenance"]["e1"]["origin"] == "manual"
        assert calls[0]["source_provenance"]["e1"]["independently_verified"] is False
    with engine.begin() as c:
        r = read_review(c, p, rr)
        assert r["ai_head_id"] is not None
        assert listing(c, p, "motion_comic")["items"] == []
        req = ApprovePublish(
            expected_lock_version=x["lock_version"],
            expected_head_id=None,
            expected_head_lock_version=None,
            reviewed_ai_decision_id=r["ai_head_id"],
            reason="真实服务隔离测试",
        )
        pub = approve_publish(c, p, uuid4(), rr, req)
        assert pub["revision_id"] == x["revision_id"]
        assert len(read_review(c, p, rr)["decisions"]) == 2
        assert len(listing(c, p, "motion_comic")["items"]) == 1


def test_knowledge_real_http_safe_projection_queue_and_atomic_guard(engine, setup):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.http import get_engine

    p = editor(engine, setup)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        client.cookies.set("cip_session", setup[2])
        session = client.get("/api/v1/session").json()["data"]
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": str(uuid4()),
        }
        response = client.post(
            "/api/v1/knowledge",
            json={
                **candidate().model_dump(mode="json"),
                "manual_source": {
                    "body_text": "人工提交的测试原文，角色选择追查。",
                    "attribution": "隔离测试材料",
                },
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        x = response.json()["data"]
        assert "org_id" not in x and "created_by" not in x["revision"]
        assert len(x["revision"]["evidence_ids"]) == 1
        identity = client.get("/api/v1/knowledge/candidates/" + x["id"])
        assert identity.status_code == 200, identity.text
        assert identity.json()["data"]["lock_version"] == x["lock_version"]
        assert identity.json()["data"]["revision_id"] == x["revision_id"]
        formal = client.get("/api/v1/knowledge?business_code=motion_comic")
        assert formal.status_code == 200, formal.text
        assert formal.json()["data"]["items"] == []
        queue = client.get("/api/v1/knowledge/candidates?business_code=motion_comic")
        assert queue.status_code == 200, queue.text
        assert queue.json()["data"]["items"][0]["revision_id"] == x["revision_id"]
        review = client.get("/api/v1/reviews/" + x["review_request_id"])
        assert review.status_code == 200, review.text
        assert review.json()["data"]["decisions"] == []
        bad = client.post(
            "/api/v1/reviews/" + x["review_request_id"] + "/approve-publication",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={
                "expected_lock_version": x["lock_version"],
                "expected_head_id": None,
                "expected_head_lock_version": None,
                "reviewed_ai_decision_id": str(uuid4()),
                "reason": "不可绕过",
            },
        )
        assert bad.status_code == 409, bad.text
        with engine.begin() as c:
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM review_decisions WHERE org_id=%s", (p.org_id,)
                ).scalar_one()
                == 0
            )
    finally:
        app.dependency_overrides.clear()


def test_extract_worker_creates_cited_candidates_and_never_formal_knowledge(
    engine, setup, tmp_path
):
    import json

    import httpx
    from pydantic import SecretStr

    from app.collection.service import insert
    from app.knowledge.contracts import ExtractCreate
    from app.knowledge.model import KnowledgeModel, output_schema, parameters
    from app.knowledge.service import listing
    from app.knowledge.tasks import KnowledgeTask, start_extract
    from app.research.analysis import start_analysis
    from app.research.analysis_contracts import AnalysisRequest
    from app.research.analysis_task import Analyze
    from app.research.stage_model import StageModel
    from app.security.primitives import digest
    from app.storage.local import LocalStore
    from app.tasks.service import Runner
    from tests.integration.test_research_analysis import analysis_ready, prepared
    from tests.integration.test_schema import approve_standard, standard

    p, _, frozen, _ = prepared(engine, setup)
    editor(engine, setup)
    analysis_ready(engine, p)

    def transport(req):
        sent = json.loads(req.content)
        value = json.loads(sent["messages"][1]["content"])
        seg = value["segments"][0]
        body = {
            "result_state": "completed",
            "coverage": "partial",
            "limitations": ["单材料局部观察"],
            "claims": [
                {
                    "key": "c",
                    "dimension": "人物设计",
                    "finding": "角色线索驱动行动",
                    "evidence": [{"segment_id": seg["id"], "quote": seg["text"]}],
                }
            ],
        }
        if "candidates" in sent["messages"][0]["content"]:
            body["candidates"] = [
                {
                    "title": "测试候选",
                    "body": "线索驱动行动，局部案例观察。",
                    "knowledge_type": "case_experience",
                    "browse_category": "dna_case",
                    "applicability": ["脚本人物动机"],
                    "limitations": "只有一个案例",
                    "claim_keys": ["c"],
                    "status": "pending_ai_review",
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": "isolate",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(body, ensure_ascii=False)},
                    }
                ],
            },
        )

    store = LocalStore(tmp_path)
    mock = httpx.MockTransport(transport)
    with engine.begin() as c:
        run = start_analysis(
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
    assert (
        Runner(
            engine,
            {
                ("research.decompose", "2"): Analyze(
                    "decompose",
                    model=StageModel(lambda: SecretStr("isolate"), transport=mock),
                    store=store,
                )
            },
        ).run(p.org_id, UUID(str(run["id"])))
        == "succeeded"
    )
    with engine.begin() as c:
        report = c.exec_driver_sql(
            "SELECT id FROM analysis_reports WHERE org_id=%s", (p.org_id,)
        ).scalar_one()
        _, rev = standard(c, p.org_id, p.member_id, kind="prompt")
        approve_standard(c, p.org_id, p.member_id, rev)
        conn = c.exec_driver_sql(
            "SELECT id FROM provider_connections WHERE org_id=%s AND provider_code='deepseek'",
            (p.org_id,),
        ).scalar_one()
        definition = {
            "model": "deepseek-flash",
            "parameters": parameters("extract"),
            "schema": output_schema("extract"),
        }
        insert(
            c,
            "ai_config_revisions",
            p.org_id,
            config_key="knowledge.extract.v2",
            version_no=1,
            task_kind="knowledge.extract",
            provider_connection_id=conn,
            model_identifier="deepseek-flash",
            prompt_revision_id=rev,
            parameters=definition["parameters"],
            output_schema=definition["schema"],
            content_sha256=digest(definition),
            created_by=p.member_id,
        )
        key = uuid4()
        req = ExtractCreate(execute_now=True, max_external_calls=1)
        task = start_extract(c, p, key, report, req)
    processor = KnowledgeTask(
        "extract", model=KnowledgeModel(lambda: SecretStr("isolate"), transport=mock), store=store
    )
    runner = Runner(engine, {("knowledge.extract", "2"): processor})
    assert runner.run(p.org_id, task["id"]) == "succeeded"
    assert runner.run(p.org_id, task["id"]) == "ignored"
    with engine.begin() as c:
        values = listing(c, p, "motion_comic", candidate=True)["items"]
        assert len(values) == 1
        assert values[0]["revision"]["source_report_id"] == report
        assert values[0]["revision"]["evidence_ids"]
        assert values[0]["state"] == "pending_ai"
        assert listing(c, p, "motion_comic")["items"] == []
        assert start_extract(c, p, key, report, req)["id"] == task["id"]


def test_failed_new_review_cannot_reuse_previous_ai_approval(engine, setup):
    from app.contracts.models import HumanDecisionCreate, PublishCreate
    from app.core.repository import create_task
    from app.intelligence.service import row
    from app.knowledge.reviews import human_decision, publish
    from app.knowledge.service import create, revision_request, state
    from app.security.errors import Denied
    from app.tasks.service import control

    p = editor(engine, setup)
    with engine.begin() as c:
        x = create(c, p, uuid4(), candidate())
        rr = revision_request(c, p, x["revision_id"])
        ai = install_ai(c, p, rr)
        h = human_decision(
            c,
            p,
            uuid4(),
            rr,
            HumanDecisionCreate(
                expected_head_id=None,
                expected_head_lock_version=None,
                reviewed_ai_decision_id=ai,
                verdict="approved",
                reason="旧人工确认",
            ),
        )
        tid, _ = create_task(
            c,
            {
                "org_id": p.org_id,
                "kind": "knowledge.review",
                "handler_version": "2",
                "knowledge_id": x["id"],
                "requested_by": p.member_id,
                "execution_authorized_by": p.member_id,
                "max_external_calls": 1,
                "idempotency_key": str(uuid4()),
                "input_sha256": "a" * 64,
            },
            [{"role": "review:none:0", "review_request_id": rr}],
        )
        control(c, row(c, "tasks", p.org_id, tid), "fail_queued", code="INVALID_INPUT")
    with engine.begin() as c:
        assert state(c, p, x["revision_id"]) == "ai_error"
    with pytest.raises(Denied, match="REVIEW_STALE"), engine.begin() as c:
        publish(
            c,
            p,
            uuid4(),
            x["id"],
            PublishCreate(
                expected_lock_version=x["lock_version"],
                revision_id=x["revision_id"],
                review_request_id=rr,
                ai_decision_id=ai,
                human_decision_id=h["id"],
            ),
        )


def test_human_evaluation_review_preserves_ai_grade_and_history(engine, setup):
    from app.collection.service import insert
    from app.contracts.models import HumanDecisionCreate, ReviewCreate
    from app.knowledge.reviews import human_decision, read_review, request_review
    from tests.integration.test_research_analysis import prepared
    from tests.integration.test_schema import ai_task, approve_standard, standard

    p, material, frozen, _ = prepared(engine, setup)
    editor(engine, setup)
    with engine.begin() as c:
        execution, tid = ai_task(
            c, p.org_id, p.member_id, material["work_id"], input_id=frozen["id"]
        )
        _, rubric = standard(c, p.org_id, p.member_id)
        approve_standard(c, p.org_id, p.member_id, rubric)
        eid = insert(
            c,
            "quality_evaluations",
            p.org_id,
            input_set_id=frozen["id"],
            task_id=tid,
            rubric_revision_id=rubric,
            ai_execution_id=execution,
            result_state="completed",
            quality_grade="A",
            dimensions={"original": "合成AI原值"},
            content_sha256="f" * 64,
        )
        c.exec_driver_sql("SELECT cip_seal('quality_evaluations',%s,%s)", (p.org_id, eid))
        r = request_review(c, p, uuid4(), ReviewCreate(purpose="evaluation_review", target_id=eid))
        approved = human_decision(
            c,
            p,
            uuid4(),
            r["id"],
            HumanDecisionCreate(
                expected_head_id=None,
                expected_head_lock_version=None,
                reviewed_ai_decision_id=None,
                verdict="approved",
                reason="初次人工确认",
            ),
        )
        view = read_review(c, p, r["id"])
        rejected = human_decision(
            c,
            p,
            uuid4(),
            r["id"],
            HumanDecisionCreate(
                expected_head_id=approved["id"],
                expected_head_lock_version=view["human_head_lock_version"],
                reviewed_ai_decision_id=None,
                verdict="rejected",
                reason="补充核对后反驳",
            ),
        )
        assert rejected["supersedes_decision_id"] == approved["id"]
        assert len(read_review(c, p, r["id"])["decisions"]) == 2
        original = (
            c.exec_driver_sql(
                "SELECT quality_grade,dimensions FROM quality_evaluations WHERE id=%s", (eid,)
            )
            .mappings()
            .one()
        )
        assert original["quality_grade"] == "A" and original["dimensions"] == {
            "original": "合成AI原值"
        }


def test_withdrawn_source_disappears_from_formal_queue_and_replay(engine, setup):
    from app.collection.service import insert
    from app.contracts.models import HumanDecisionCreate, PublishCreate
    from app.knowledge.reviews import human_decision, publish
    from app.knowledge.service import create, listing, published, revision_request
    from app.security.errors import Denied
    from tests.integration.test_schema import raw

    p = editor(engine, setup)
    key = uuid4()
    with engine.begin() as c:
        source = raw(c, p.org_id, p.member_id)
        ref = insert(c, "evidence_refs", p.org_id, raw_asset_id=source, locator_kind="whole")
        x = create(c, p, key, candidate(evidence_ids=[ref]))
        rr = revision_request(c, p, x["revision_id"])
        ai = install_ai(c, p, rr)
        h = human_decision(
            c,
            p,
            uuid4(),
            rr,
            HumanDecisionCreate(
                expected_head_id=None,
                expected_head_lock_version=None,
                reviewed_ai_decision_id=ai,
                verdict="approved",
                reason="隔离批准",
            ),
        )
        publish(
            c,
            p,
            uuid4(),
            x["id"],
            PublishCreate(
                expected_lock_version=x["lock_version"],
                revision_id=x["revision_id"],
                review_request_id=rr,
                ai_decision_id=ai,
                human_decision_id=h["id"],
            ),
        )
        insert(
            c,
            "raw_asset_events",
            p.org_id,
            raw_asset_id=source,
            event_no=1,
            event_kind="withdrawn",
            reason="撤回测试",
            actor_member_id=p.member_id,
        )
    with engine.begin() as c:
        assert listing(c, p, "motion_comic")["items"] == []
        assert listing(c, p, "motion_comic", candidate=True)["items"] == []
    with pytest.raises(Denied), engine.begin() as c:
        published(c, p, x["id"])
    with pytest.raises(Denied), engine.begin() as c:
        create(c, p, key, candidate(evidence_ids=[ref]))


def test_reviewer_can_request_ai_without_editor_permission(engine, setup):
    from app.contracts.models import ReviewCreate
    from app.knowledge.reviews import request_review
    from app.knowledge.service import create
    from app.security.errors import Denied

    p = editor(engine, setup)
    with engine.begin() as c:
        x = create(c, p, uuid4(), candidate())
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s",
            (p.org_id, p.member_id),
        )
        grant(
            c,
            p.org_id,
            p.member_id,
            p.member_id,
            [
                "content.read",
                "evidence.read",
                "knowledge.candidate.read",
                "knowledge.review.run",
                "standard.read",
            ],
        )
    # No edit grant is required to reach the explicit AI configuration gate.
    with pytest.raises(Denied, match="MODEL_NOT_CONFIGURED"), engine.begin() as c:
        request_review(
            c,
            p,
            uuid4(),
            ReviewCreate(
                purpose="knowledge_release",
                target_id=x["revision_id"],
                execute_ai=True,
                max_external_calls=1,
            ),
        )


def test_manual_source_revision_replaces_only_its_previous_submitted_original(engine, setup):
    from app.knowledge.contracts import KnowledgeRevisionWrite, KnowledgeWrite
    from app.knowledge.service import create, read_candidate, revise

    p = editor(engine, setup)
    source = {"body_text": "第一段原文，角色转身调查。", "attribution": "人工提供授权剧本"}
    with engine.begin() as c:
        first = create(
            c, p, uuid4(), KnowledgeWrite(**candidate().model_dump(), manual_source=source)
        )
        original = first["revision"]["evidence_ids"]
        assert len(original) == 1
        req = KnowledgeRevisionWrite(
            **{**candidate().model_dump(), "evidence_ids": original},
            manual_source={**source, "body_text": "修订后的原文，角色放弃调查。"},
            expected_lock_version=first["lock_version"],
            revision_reason="替换原文",
        )
        newer = revise(c, p, uuid4(), first["id"], req)
        assert len(newer["evidence_ids"]) == 1 and newer["evidence_ids"] != original
        assert read_candidate(c, p, first["revision_id"])["evidence_ids"] == original
        row = (
            c.exec_driver_sql(
                "SELECT r.body_text,r.origin,e.quoted_text FROM evidence_refs e JOIN raw_assets r ON r.id=e.raw_asset_id AND r.org_id=e.org_id WHERE e.id=%s",
                (newer["evidence_ids"][0],),
            )
            .mappings()
            .one()
        )
        assert row["quoted_text"] == "修订后的原文，角色放弃调查。"
        assert "【人工提供出处，未独立核验】\n人工提供授权剧本" in row["body_text"]
        assert row["origin"] == "manual"
