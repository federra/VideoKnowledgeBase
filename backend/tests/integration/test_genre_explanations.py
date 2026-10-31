"""Disposable PG and fake provider only; immutable originals and source boundaries."""

from uuid import UUID, uuid4

import pytest

from app.knowledge import genre_explanations as g
from app.knowledge import service
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.tasks.service import Runner
from tests.integration.test_knowledge import editor
from tests.integration.test_topics import configured, handler_for

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def fixture(engine, setup, monkeypatch, tmp_path):
    from app.knowledge.legacy_import import import_rows, parse_genres

    p = configured(engine, setup, monkeypatch)
    editor(engine, setup)
    text = "# 模块16 · 海外本土化 + 140+题材库\n### 都市男频\nM01 · 合成题材\n## 四、A↔B对应速查表"
    with engine.begin() as c:
        imported = import_rows(
            c,
            p,
            parse_genres(text),
            source_text=text,
            source_name="K10.md",
            category="genre",
            reason="合成测试导入",
        )
        item = service.published(c, p, UUID(imported["ids"][0]))
    calls = []
    output = {
        "items": [
            {
                "revision_id": str(item["revision_id"]),
                "explanation": "以都市人物的成长与利益冲突推动故事。",
            }
        ]
    }
    template = handler_for(tmp_path, output, calls)
    handler = g.Explain(template.model, template.store)
    monkeypatch.setattr("app.storage.http.get_store", lambda: template.store)
    return p, item, handler, calls


def test_gloss_once_formal_read_preserves_revision_and_source_revocation(
    engine, setup, monkeypatch, tmp_path
):
    p, item, handler, calls = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c:
        task = g.start(c, p, [item["revision_id"]], "user requested", handler=handler)
        assert g.start(c, p, [item["revision_id"]], "user requested", handler=handler) == task
    runner = Runner(engine, {(g.KIND, g.VERSION): handler}, lease_seconds=720)
    assert runner.run(p.org_id, UUID(task["id"])) == "succeeded"
    runner.run(p.org_id, UUID(task["id"]))
    assert len(calls) == 1
    with engine.begin() as c:
        got = service.published(c, p, item["id"])
        assert (
            got["revision"] == item["revision"] and got["publication_id"] == item["publication_id"]
        )
        assert got["ai_explanation"]["text"] == "以都市人物的成长与利益冲突推动故事。"
        assert got["ai_explanation"]["revision_id"] == item["revision_id"]
        assert (
            service.listing(c, p, "story_short")["items"][0]["ai_explanation"]
            == got["ai_explanation"]
        )
        raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM task_outputs WHERE org_id=%s AND task_id=%s AND role='genre_explanations'",
            (p.org_id, UUID(task["id"])),
        ).scalar_one()
        assert Authorizer(c, p).read("raw_assets", raw)
        source = c.exec_driver_sql(
            "SELECT raw_asset_id FROM evidence_refs WHERE org_id=%s AND id=%s",
            (p.org_id, item["revision"]["evidence_ids"][0]),
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason,actor_member_id) VALUES (%s,%s,%s,1,'withdrawn','test',%s)",
            (uuid4(), p.org_id, source, p.member_id),
        )
    with engine.begin() as c:
        with pytest.raises(Denied):
            Authorizer(c, p).read("raw_assets", raw)
        assert service.listing(c, p, "motion_comic")["items"] == []


def test_gloss_stale_publication_rejected_and_recycle_blocks_raw(
    engine, setup, monkeypatch, tmp_path
):
    p, item, handler, _calls = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c:
        task = g.start(c, p, [item["revision_id"]], "user requested", handler=handler)
    assert (
        Runner(engine, {(g.KIND, g.VERSION): handler}, lease_seconds=720).run(
            p.org_id, UUID(task["id"])
        )
        == "succeeded"
    )
    with engine.begin() as c:
        raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM task_outputs WHERE org_id=%s AND task_id=%s AND role='genre_explanations'",
            (p.org_id, UUID(task["id"])),
        ).scalar_one()
        # Test provisioner marks recycle; no destructive operation, disposable org only.
        c.exec_driver_sql(
            "UPDATE knowledge_items SET recycled_at=clock_timestamp(),recycled_by=%s,lock_version=lock_version+1 WHERE org_id=%s AND id=%s",
            (p.member_id, p.org_id, item["id"]),
        )
    with engine.begin() as c:
        with pytest.raises(Denied):
            Authorizer(c, p).read("raw_assets", raw)
        with pytest.raises(Denied):
            g.start(c, p, [item["revision_id"]], "different request", handler=handler)


def test_private_files_inherit_knowledge_source_revocation(engine, setup, monkeypatch, tmp_path):
    from tests.integration.test_security import grant

    p, item, handler, _calls = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c:
        grant(c, p.org_id, p.member_id, p.member_id, ["file.read"])
        task = g.start(c, p, [item["revision_id"]], "user requested", handler=handler)
    assert (
        Runner(engine, {(g.KIND, g.VERSION): handler}, lease_seconds=720).run(
            p.org_id, UUID(task["id"])
        )
        == "succeeded"
    )
    with engine.begin() as c:
        files = c.exec_driver_sql(
            "SELECT input_manifest_file_id,output_file_id FROM ai_executions WHERE org_id=%s AND task_id=%s",
            (p.org_id, UUID(task["id"])),
        ).one()
        assert all(Authorizer(c, p).file(fid) for fid in files)
        source = c.exec_driver_sql(
            "SELECT raw_asset_id FROM evidence_refs WHERE org_id=%s AND id=%s",
            (p.org_id, item["revision"]["evidence_ids"][0]),
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason,actor_member_id) VALUES (%s,%s,%s,1,'withdrawn','test',%s)",
            (uuid4(), p.org_id, source, p.member_id),
        )
    with engine.begin() as c:
        for fid in files:
            with pytest.raises(Denied):
                Authorizer(c, p).file(fid)
            with pytest.raises(Denied):
                Authorizer(c, p).read("file_objects", fid)


def test_shared_target_needs_edit_on_every_business(engine, setup, monkeypatch, tmp_path):
    p, item, _handler, _calls = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c:
        az = Authorizer(c, p)
        original = az.allowed
        az.allowed = lambda action, scopes: (
            (("business", "motion_comic") in scopes)
            if action == "knowledge.edit"
            else original(action, scopes)
        )
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            g.target(c, p, item["revision_id"], edit=True, az=az)


def test_existing_application_grants_are_sufficient(engine, setup, monkeypatch, tmp_path):
    from sqlalchemy import event

    from app.core.database import build_engine
    from app.core.database_roles import grant_application

    p, item, handler, calls = fixture(engine, setup, monkeypatch, tmp_path)
    role = "cip_test_gloss_" + uuid4().hex
    with engine.begin() as c:
        c.exec_driver_sql(
            "CREATE ROLE " + role + " NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
        )
        grant_application(c.connection.driver_connection.cursor(), role)
    restricted = build_engine(engine.url)

    @event.listens_for(restricted, "connect")
    def effective_app_role(dbapi, _record):
        dbapi.execute("SET ROLE " + role)

    try:
        with restricted.begin() as c:
            task = g.start(c, p, [item["revision_id"]], "user requested", handler=handler)
        assert (
            Runner(restricted, {(g.KIND, g.VERSION): handler}, lease_seconds=720).run(
                p.org_id, UUID(task["id"])
            )
            == "succeeded"
        )
        with restricted.begin() as c:
            assert service.published(c, p, item["id"])["ai_explanation"]["text"]
        assert len(calls) == 1
    finally:
        restricted.dispose()
        with engine.begin() as c:
            c.exec_driver_sql("DROP OWNED BY " + role)
            c.exec_driver_sql("DROP ROLE " + role)


def test_read_only_genre_dependencies_are_prefetched_once(engine, setup, monkeypatch, tmp_path):
    import hashlib
    from datetime import UTC, datetime

    from sqlalchemy import event

    from app.collection.service import insert
    from app.security.read_authorizer import ReadAuthorizer

    p, _item, _handler, _calls = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c:
        ids = []
        for n in range(3):
            body = '{"synthetic":' + str(n) + "}"
            ids.append(
                insert(
                    c,
                    "raw_assets",
                    p.org_id,
                    origin="manual",
                    asset_kind="response",
                    submitted_by=p.member_id,
                    body_text=body,
                    sha256=hashlib.sha256(body.encode()).hexdigest(),
                    captured_at=datetime.now(UTC),
                )
            )
    observed = []

    def count(_c, _cur, statement, _parameters, _context, _many):
        if "kind='knowledge.genre_explain'" in statement:
            observed.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        with engine.begin() as c:
            az = ReadAuthorizer(c, p)
            for rid in ids:
                assert az.read("raw_assets", rid)
        assert len(observed) == 1
    finally:
        event.remove(engine, "before_cursor_execute", count)
