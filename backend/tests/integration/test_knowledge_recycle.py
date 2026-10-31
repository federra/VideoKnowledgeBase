"""Disposable knowledge recycling; never mutate real workspace knowledge."""

from uuid import uuid4

import pytest

from tests.integration.test_knowledge import editor
from tests.integration.test_security import grant

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def samples(engine, setup):
    from app.knowledge.legacy_import import import_rows, parse_quotes
    from app.knowledge.service import listing

    p = editor(engine, setup)
    text = '## 二、共鸣金句库\n#### 男频 · 守护\n1. "测试甲。"\n2. "测试乙。"\n## 三、18爽点内核库'
    with engine.begin() as c:
        import_rows(
            c,
            p,
            parse_quotes(text),
            source_text=text,
            source_name="isolated.md",
            category="quote",
            reason="隔离测试",
        )
        return p, listing(c, p, "motion_comic")["items"]


def request(items):
    from app.knowledge.contracts import KnowledgeRecycleWrite

    return KnowledgeRecycleWrite(
        items=[{"id": x["id"], "expected_lock_version": x["lock_version"]} for x in items]
    )


def test_recycle_batch_hides_formal_and_versions_restores_exact_publication_and_replays(
    engine, setup
):
    from app.knowledge.recycle import change, listing
    from app.knowledge.service import listing as formal
    from app.knowledge.service import published
    from app.security.authorization import Authorizer
    from app.security.errors import Denied

    p, items = samples(engine, setup)
    key = uuid4()
    with engine.begin() as c:
        before = c.exec_driver_sql(
            "SELECT authz_version FROM organizations WHERE id=%s", (p.org_id,)
        ).scalar_one()
        result = change(c, p, key, request(items))
        assert change(c, p, key, request(items)) == result
        assert len(result["ids"]) == 2
        assert formal(c, p, "motion_comic")["items"] == []
        assert formal(c, p, "story_short")["items"] == []
        assert (
            c.exec_driver_sql(
                "SELECT authz_version FROM organizations WHERE id=%s", (p.org_id,)
            ).scalar_one()
            > before
        )
        recycled = listing(c, p, "motion_comic")["items"]
        assert len(recycled) == 2 and all(x["recycled_at"] for x in recycled)
    for item in items:
        with pytest.raises(Denied, match="NOT_FOUND"), engine.begin() as c:
            published(c, p, item["id"])
        with pytest.raises(Denied, match="NOT_FOUND"), engine.begin() as c:
            Authorizer(c, p).read("knowledge_revisions", item["revision_id"])
    with engine.begin() as c:
        change(c, p, uuid4(), request(recycled), restore=True)
        restored = formal(c, p, "motion_comic")["items"]
        assert {x["publication_id"] for x in restored} == {x["publication_id"] for x in items}
        assert listing(c, p, "motion_comic")["items"] == []
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM audit_events WHERE org_id=%s AND action_code='knowledge.recycled'",
                (p.org_id,),
            ).scalar_one()
            == 2
        )


def test_recycle_stale_batch_and_cross_org_are_atomic(engine, setup):
    from app.knowledge.recycle import change
    from app.knowledge.service import listing

    p, items = samples(engine, setup)
    wrong = request(items).model_copy(deep=True)
    wrong.items[1].expected_lock_version = "999"
    with pytest.raises(Exception, match="VERSION_CONFLICT"), engine.begin() as c:
        change(c, p, uuid4(), wrong)
    wrong.items[1].id = uuid4()
    from app.security.errors import Denied

    with pytest.raises(Denied), engine.begin() as c:
        change(c, p, uuid4(), wrong)
    with engine.begin() as c:
        assert listing(c, p, "motion_comic")["total"] == "2"


def test_recycle_requires_edit_in_all_shared_businesses_and_source_access(engine, setup):
    from app.knowledge.recycle import change, listing
    from app.security.errors import Denied
    from app.security.sessions import MemberPrincipal
    from tests.integration.test_schema import execute

    p, items = samples(engine, setup)
    member = uuid4()
    with engine.begin() as c:
        execute(
            c,
            "INSERT INTO members(id,org_id,login_name,display_name,password_hash) VALUES(%s,%s,%s,%s,%s)",
            (member, p.org_id, "reader", "reader", "unused"),
        )
        grant(
            c,
            p.org_id,
            p.member_id,
            member,
            ["content.read", "evidence.read", "knowledge.edit"],
            scope="business",
            target="motion_comic",
        )
    limited = MemberPrincipal(p.org_id, member)
    with pytest.raises(Denied), engine.begin() as c:
        change(c, limited, uuid4(), request(items))
    with engine.begin() as c:
        change(c, p, uuid4(), request(items))
        assert listing(c, limited, "motion_comic")["items"] == []
        frozen = request(listing(c, p, "motion_comic")["items"])
        raw = c.exec_driver_sql(
            "SELECT r.raw_asset_id FROM knowledge_evidence e JOIN evidence_refs r ON r.org_id=e.org_id AND r.id=e.evidence_id WHERE e.org_id=%s AND e.revision_id=%s",
            (p.org_id, items[0]["revision_id"]),
        ).scalar_one()
        execute(
            c,
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','isolated')",
            (p.org_id, raw),
        )
    with pytest.raises(Denied), engine.begin() as c:
        change(c, p, uuid4(), frozen, restore=True)


def test_recycle_real_http_csrf_projection_and_restore(engine, setup):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security.http import get_engine

    _, items = samples(engine, setup)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        client.cookies.set("cip_session", setup[2])
        csrf = client.get("/api/v1/session").json()["data"]["csrf_token"]
        body = request(items).model_dump(mode="json")
        assert client.post("/api/v1/knowledge/recycle", json=body).status_code == 403
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": str(uuid4()),
        }
        result = client.post("/api/v1/knowledge/recycle", json=body, headers=headers)
        assert result.status_code == 200, result.text
        bin_response = client.get("/api/v1/knowledge/recycle-bin?business_code=motion_comic")
        assert bin_response.status_code == 200, bin_response.text
        recycled = bin_response.json()["data"]["items"]
        assert len(recycled) == 2 and recycled[0]["recycled_at"]
        assert "recycled_by" not in recycled[0]
        assert (
            client.get("/api/v1/knowledge?business_code=motion_comic").json()["data"]["items"] == []
        )
        headers["Idempotency-Key"] = str(uuid4())
        result = client.post(
            "/api/v1/knowledge/restore",
            json=request(recycled).model_dump(mode="json"),
            headers=headers,
        )
        assert result.status_code == 200, result.text
        assert (
            client.get("/api/v1/knowledge?business_code=motion_comic").json()["data"]["total"]
            == "2"
        )
    finally:
        app.dependency_overrides.clear()
