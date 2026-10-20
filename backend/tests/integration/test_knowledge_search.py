"""S07.5 real disposable PG; no external provider calls or project records."""

from uuid import UUID, uuid4

import pytest

from tests.integration.test_knowledge import candidate, editor, install_ai

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def release(c, p):
    from app.knowledge.contracts import ApprovePublish, KnowledgeWrite
    from app.knowledge.reviews import approve_publish
    from app.knowledge.service import create

    req = KnowledgeWrite(
        **{**candidate().model_dump(), "title": "ＡＩ人物线索", "limitations": "仅适用授权片段"},
        manual_source={"body_text": "角色发现线索后转身调查。", "attribution": "隔离授权文本"},
    )
    x = create(c, p, uuid4(), req)
    aid = install_ai(c, p, x["review_request_id"])
    pub = approve_publish(
        c,
        p,
        uuid4(),
        x["review_request_id"],
        ApprovePublish(
            expected_lock_version=str(x["lock_version"]),
            expected_head_id=None,
            expected_head_lock_version=None,
            reviewed_ai_decision_id=aid,
            reason="隔离人工批准",
        ),
    )
    x["lock_version"] = c.exec_driver_sql(
        "SELECT lock_version FROM knowledge_items WHERE org_id=%s AND id=%s", (p.org_id, x["id"])
    ).scalar_one()
    return x, pub


def test_search_normalizes_fullwidth_and_searches_limitations(engine, setup):
    from app.knowledge.service import listing

    p = editor(engine, setup)
    with engine.begin() as c:
        x, _ = release(c, p)
        assert listing(c, p, "motion_comic", q="  ai人物  ")["items"][0]["id"] == x["id"]
        assert listing(c, p, "motion_comic", q="授权片段")["items"][0]["id"] == x["id"]
        assert listing(c, p, "story_short", q="人物")["items"] == []
        assert listing(c, p, "motion_comic", category="genre")["items"] == []


def test_exact_sources_and_formal_index_survive_candidate_revision_but_not_withdrawal(
    engine, setup
):
    from app.collection.service import insert
    from app.knowledge.contracts import KnowledgeRevisionWrite
    from app.knowledge.provenance import sources
    from app.knowledge.search import index_publication
    from app.knowledge.service import revise
    from app.security.errors import Denied

    p = editor(engine, setup)
    with engine.begin() as c:
        x, pub = release(c, p)
        rid = UUID(str(x["revision_id"]))
        first = sources(c, p, rid)
        assert (
            first["revision_id"] == rid
            and first["items"][0]["quoted_text"] == "角色发现线索后转身调查。"
        )
        assert (
            first["items"][0]["origin"] == "manual"
            and first["items"][0]["independently_verified"] is False
        )
        doc = index_publication(c, p, pub["id"])
        assert index_publication(c, p, pub["id"]) == doc
        newer = revise(
            c,
            p,
            uuid4(),
            x["id"],
            KnowledgeRevisionWrite(
                **{**candidate().model_dump(), "title": "另一个候选"},
                expected_lock_version=str(x["lock_version"]),
                revision_reason="新候选",
            ),
        )
        assert sources(c, p, newer["id"])["items"] == []
        assert sources(c, p, rid)["items"][0]["quoted_text"] == "角色发现线索后转身调查。"
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM search_documents WHERE revision_id=%s", (newer["id"],)
            ).scalar_one()
            == 0
        )
        raw = first["items"][0]["raw_asset_id"]
        insert(
            c,
            "raw_asset_events",
            p.org_id,
            raw_asset_id=raw,
            event_no=1,
            event_kind="withdrawn",
            reason="撤回",
            actor_member_id=p.member_id,
        )
    with pytest.raises(Denied), engine.begin() as c:
        sources(c, p, rid)
    with pytest.raises(Denied), engine.begin() as c:
        index_publication(c, p, pub["id"])


def test_source_http_projects_only_authorized_version(engine, setup):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.http import get_engine

    p = editor(engine, setup)
    with engine.begin() as c:
        x, _ = release(c, p)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        client.cookies.set("cip_session", setup[2])
        resp = client.get("/api/v1/knowledge/revisions/" + str(x["revision_id"]) + "/sources")
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["items"][0]["quoted_text"] == "角色发现线索后转身调查。"
        assert "submitted_by" not in str(body) and "org_id" not in str(body)
        assert (
            client.get("/api/v1/knowledge/revisions/" + str(uuid4()) + "/sources").status_code
            == 404
        )
    finally:
        app.dependency_overrides.clear()


def test_vector_interface_uses_current_authorized_model_space(engine, setup):
    from app.collection.service import insert
    from app.knowledge.search import document
    from app.knowledge.vectors import EmbeddingConfig, chunks, nearest, store

    p = editor(engine, setup)
    cfg = EmbeddingConfig("test-only", "v1", 2)
    with engine.begin() as c:
        x, pub = release(c, p)
        store(c, p, pub["id"], cfg, [[1.0, 0.0] for _ in chunks(document(x["revision"]))])
        assert nearest(c, p, "motion_comic", cfg, [1.0, 0.0])[0]["item"]["id"] == x["id"]
        assert nearest(c, p, "story_short", cfg, [1.0, 0.0]) == []
        assert (
            nearest(c, p, "motion_comic", EmbeddingConfig("test-only", "v2", 2), [1.0, 0.0]) == []
        )
        raw = c.exec_driver_sql(
            "SELECT e.raw_asset_id FROM evidence_refs e JOIN knowledge_evidence k ON k.org_id=e.org_id AND k.evidence_id=e.id WHERE k.revision_id=%s",
            (x["revision_id"],),
        ).scalar_one()
        insert(
            c,
            "raw_asset_events",
            p.org_id,
            raw_asset_id=raw,
            event_no=1,
            event_kind="withdrawn",
            reason="撤回",
            actor_member_id=p.member_id,
        )
        assert nearest(c, p, "motion_comic", cfg, [1.0, 0.0]) == []


def test_parsed_source_resolves_its_exact_material_without_report(engine, setup):
    from app.knowledge.provenance import sources
    from app.knowledge.service import create
    from app.processing.research import Parse
    from app.research.service import direct_intake
    from app.tasks.service import Runner
    from tests.integration.test_research_intake import request

    p = editor(engine, setup)
    with engine.begin() as c:
        m = direct_intake(c, p, uuid4(), request())
    assert (
        Runner(engine, {("research.parse", "1"): Parse()}).run(p.org_id, m["task_id"])
        == "succeeded"
    )
    with engine.begin() as c:
        eid = c.exec_driver_sql(
            "SELECT e.id FROM evidence_refs e JOIN raw_assets r ON r.org_id=e.org_id AND r.id=e.raw_asset_id WHERE r.parent_artifact_version_id=%s LIMIT 1",
            (m["artifact_version_id"],),
        ).scalar_one()
        x = create(c, p, uuid4(), candidate(evidence_ids=[eid]))
        row = sources(c, p, x["revision_id"])["items"][0]
        assert row["target_artifact_version_id"] == m["artifact_version_id"]
        assert row["work_id"] == m["work_id"] and row["material_version_no"] == 1
        assert row["business_code"] == "motion_comic"
