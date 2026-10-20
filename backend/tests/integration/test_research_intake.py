"""S07.2 real transactional ingestion and parsing; no external calls."""

from uuid import uuid4

import pytest

from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def principal(engine, setup):
    from app.security.sessions import MemberPrincipal

    org, member, *_ = setup
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            [
                "content.read",
                "content.write",
                "evidence.read",
                "file.read",
                "research.submit",
                "task.read",
                "task.manage",
            ],
        )
    return MemberPrincipal(org, member)


def request():
    from app.research.contracts import DirectIntake

    return DirectIntake.model_validate(
        {
            "target": {
                "kind": "new",
                "business_code": "motion_comic",
                "name": "真实文本测试",
                "genre_tags": ["悬疑"],
                "total_episode_count": 5,
            },
            "title": "第2集脚本",
            "material_kind": "script",
            "origin": "text",
            "body_text": "第一段：主角发现线索。\n第二段：门外传来脚步声。",
            "episode_no": 2,
        }
    )


def test_research_intake_versions_dedup_and_exact_parse_evidence(engine, setup):
    from app.processing.research import Parse
    from app.research.contracts import MaterialIntake
    from app.research.service import add_material, detail, direct_intake
    from app.tasks.service import Runner

    p = principal(engine, setup)
    key = uuid4()
    req = request()
    with engine.begin() as c:
        out = direct_intake(c, p, key, req)
        assert direct_intake(c, p, key, req) == out
        initial = detail(c, p, out["work_id"])
        assert initial["collected_units"] == 1 and initial["analyzed_units"] == 0
        assert [u["episode_no"] for u in initial["units"]] == [2]
    runner = Runner(engine, {("research.parse", "1"): Parse()})
    assert runner.run(p.org_id, out["task_id"]) == "succeeded"
    assert runner.run(p.org_id, out["task_id"]) == "ignored"
    with engine.begin() as c:
        got = detail(c, p, out["work_id"])
        assert got["materials"][0]["parsing"]["result_state"] == "completed"
        assert len(got["materials"][0]["parsing"]["paragraphs"]) == 2
        assert got["materials"][0]["parsing"]["paragraphs"][1]["text"] == "第二段：门外传来脚步声。"
        material = got["materials"][0]
        again = MaterialIntake(
            title="第2集脚本",
            material_kind="script",
            origin="text",
            body_text=req.body_text,
            episode_no=2,
            artifact_id=material["id"],
            expected_artifact_lock_version=material["lock_version"],
        )
        same = add_material(c, p, uuid4(), out["work_id"], again)
        assert same["artifact_version_id"] == out["artifact_version_id"]
        newer = again.model_copy(update={"body_text": "修订：主角在门后发现第二条线索。"})
        changed = add_material(c, p, uuid4(), out["work_id"], newer)
        assert changed["artifact_version_id"] != out["artifact_version_id"]
    with engine.begin() as c:
        got = detail(c, p, out["work_id"])
        assert got["collected_units"] == 1 and len(got["materials"]) == 1
        assert len(got["materials"][0]["versions"]) == 2
        old = c.exec_driver_sql(
            "SELECT body_text FROM artifact_versions WHERE id=%s", (out["artifact_version_id"],)
        ).scalar_one()
        assert old == req.body_text
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM analysis_reports WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )


def test_intelligence_intake_preserves_handoff_assessment_and_source_dedup(engine, setup):
    from app.processing.research import Parse
    from app.research.contracts import IntelligenceIntake
    from app.research.service import detail, intelligence_intake
    from app.security.errors import Denied
    from app.tasks.service import Runner
    from tests.integration.test_research_probe import seed

    p, _snap, entry = seed(engine, setup)
    with engine.begin() as c:
        grant(
            c, p.org_id, p.member_id, p.member_id, ["research.submit", "content.write", "file.read"]
        )
    req = IntelligenceIntake.model_validate(
        {
            "snapshot_entry_id": str(entry),
            "target": {
                "kind": "new",
                "business_code": "motion_comic",
                "name": "短剧0",
                "genre_tags": ["都市"],
            },
            "confirmed_business_code": "motion_comic",
            "material_kind": "reference",
            "assessment": {
                "quality_grade": "A",
                "genre_tags": ["都市"],
                "learning_tags": ["冲突设计"],
                "additional_learning": "简介中的身份冲突",
            },
        }
    )
    with engine.begin() as c:
        result = intelligence_intake(c, p, uuid4(), req)
        again = intelligence_intake(c, p, uuid4(), req)
        assert again["work_id"] == result["work_id"] and again["task_id"] == result["task_id"]
        assert again["submission_id"] != result["submission_id"] and again["reused"]
        stored = c.exec_driver_sql(
            "SELECT handoff_id FROM research_submissions WHERE id=%s", (result["submission_id"],)
        ).scalar_one()
        assert stored is not None
        assert (
            c.exec_driver_sql(
                "SELECT quality_grade FROM preliminary_assessments WHERE submission_id=%s",
                (result["submission_id"],),
            ).scalar_one()
            == "A"
        )
    assert (
        Runner(engine, {("research.parse", "1"): Parse()}).run(p.org_id, result["task_id"])
        == "succeeded"
    )
    with engine.begin() as c:
        data = detail(c, p, result["work_id"])
        assert data["collected_units"] == 0 and data["analyzed_units"] == 0
        assert data["materials"][0]["versions"][0]["material_kind"] == "reference"
        with pytest.raises(Denied):
            intelligence_intake(
                c, p, uuid4(), req.model_copy(update={"material_kind": "finished_video"})
            )


def test_research_http_upload_reference_csrf_and_postcommit_dispatch(
    engine, setup, tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.processing.research import Parse
    from app.security.http import get_engine
    from app.security.sessions import csrf_for
    from app.storage.http import get_store
    from app.storage.local import LocalStore
    from app.tasks.service import Runner

    p = principal(engine, setup)
    queued = []

    def dispatch(org, tid):
        # Another connection observes the committed row before a message is sent.
        with engine.connect() as c:
            assert (
                c.exec_driver_sql(
                    "SELECT id FROM tasks WHERE org_id=%s AND id=%s", (org, tid)
                ).scalar_one()
                == tid
            )
        queued.append(tid)

    monkeypatch.setattr("app.research.worker.dispatch_parse", dispatch)
    store = LocalStore(tmp_path / "files")
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app, base_url="http://localhost:8000")
        client.cookies.set("cip_session", setup[2], path="/api/v1")
        headers = {
            "Origin": "http://localhost:5173",
            "X-CSRF-Token": csrf_for(setup[2]),
            "Idempotency-Key": str(uuid4()),
        }
        body = {"business_code": "motion_comic", "name": "上传测试", "genre_tags": []}
        assert (
            client.post(
                "/api/v1/works", json=body, headers={"Origin": headers["Origin"]}
            ).status_code
            == 403
        )
        created = client.post("/api/v1/works", json=body, headers=headers)
        assert created.status_code == 201, created.text
        work = created.json()["data"]
        wid = work["id"]
        uploaded = client.post(
            "/api/v1/files",
            content="上传段落一\n上传段落二".encode(),
            params={
                "work_id": wid,
                "expected_work_lock_version": work["lock_version"],
                "original_name": "authorized.txt",
                "media_type": "text/plain",
            },
            headers={
                **headers,
                "Idempotency-Key": str(uuid4()),
                "Content-Type": "application/octet-stream",
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        material = {
            "title": "上传文本",
            "origin": "upload",
            "file_id": uploaded.json()["data"]["id"],
            "material_kind": "script",
            "episode_no": 2,
        }
        key = str(uuid4())
        h = {**headers, "Idempotency-Key": key}
        first = client.post(f"/api/v1/works/{wid}/materials", json=material, headers=h)
        assert first.status_code == 202, first.text
        replay = client.post(f"/api/v1/works/{wid}/materials", json=material, headers=h)
        assert replay.json()["data"] == first.json()["data"]
        assert (
            client.post(
                f"/api/v1/works/{wid}/materials", json={**material, "title": "不同输入"}, headers=h
            ).status_code
            == 409
        )
        tid = __import__("uuid").UUID(first.json()["data"]["task_id"])
        assert tid in queued
        assert (
            Runner(engine, {("research.parse", "1"): Parse(store)}).run(p.org_id, tid)
            == "succeeded"
        )
        got = client.get(f"/api/v1/works/{wid}")
        assert got.status_code == 200, got.text
        assert (
            got.json()["data"]["materials"][0]["parsing"]["paragraphs"][1]["text"] == "上传段落二"
        )
        with engine.begin() as c:
            c.exec_driver_sql(
                "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s",
                (p.org_id, p.member_id),
            )
        assert client.post(
            f"/api/v1/works/{wid}/materials", json=material, headers=h
        ).status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()
        store.close()


def test_research_unavailable_link_bounds_and_parse_failure_leave_no_false_analysis(engine, setup):
    from app.processing.research import Parse
    from app.research.service import detail, direct_intake
    from app.security.errors import Denied
    from app.tasks.service import Runner

    p = principal(engine, setup)
    bad = request().model_copy(
        update={"origin": "link", "body_text": None, "url": "https://example.com/not-captured"}
    )
    with pytest.raises(Denied, match="SOURCE_UNAVAILABLE"), engine.begin() as c:
        direct_intake(c, p, uuid4(), bad)
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM works WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
    with pytest.raises(Denied, match="VALIDATION_FAILED"), engine.begin() as c:
        direct_intake(c, p, uuid4(), request().model_copy(update={"episode_no": 6}))
    with engine.begin() as c:
        out = direct_intake(
            c, p, uuid4(), request().model_copy(update={"body_text": "bad\x01text"})
        )
    assert (
        Runner(engine, {("research.parse", "1"): Parse()}).run(p.org_id, out["task_id"]) == "failed"
    )
    with engine.begin() as c:
        data = detail(c, p, out["work_id"])
        assert data["materials"][0]["parsing"]["state"] == "failed"
        assert data["materials"][0]["parsing"]["paragraphs"] == []
        assert data["analyzed_units"] == 0
