"""Real PG import, publication isolation and source revocation; no model calls."""

from uuid import uuid4

import pytest

from tests.integration.test_knowledge import editor

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_legacy_import_is_formal_idempotent_and_revision_stays_pending(engine, setup):
    from app.knowledge.contracts import KnowledgeRevisionWrite
    from app.knowledge.legacy_import import import_rows, parse_quotes
    from app.knowledge.service import listing, revise

    p = editor(engine, setup)
    text = '## 二、共鸣金句库\n#### 男频 · 守护\n1. "守护。"\n## 三、18爽点内核库'
    rows = parse_quotes(text)
    with engine.begin() as c:
        result = import_rows(
            c,
            p,
            rows,
            source_text=text,
            source_name="K09.md",
            category="quote",
            reason="用户确认直接导入",
        )
        assert result["created"] == 1
    with engine.begin() as c:
        assert (
            import_rows(
                c,
                p,
                rows,
                source_text=text,
                source_name="K09.md",
                category="quote",
                reason="用户确认直接导入",
            )["created"]
            == 0
        )
        items = listing(c, p, "motion_comic")["items"]
        assert len(items) == 1
        item = items[0]
        assert item["release_mode"] == "legacy_import"
        assert listing(c, p, "story_short")["total"] == "1"
        assert listing(c, p, "ecommerce_video")["total"] == "0"
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM review_decisions WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM search_documents WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 1
        )
        req = KnowledgeRevisionWrite(
            title="修订后",
            body_text="修订文本",
            knowledge_type="content_atom",
            browse_category="quote",
            business_codes=["motion_comic"],
            evidence_ids=item["revision"]["evidence_ids"],
            expected_lock_version=item["lock_version"],
            revision_reason="测试新版本",
        )
        revise(c, p, uuid4(), item["id"], req)
        assert listing(c, p, "motion_comic")["items"][0]["title"] == "守护。"
        assert listing(c, p, "motion_comic", candidate=True)["items"][0]["state"] == "pending_ai"
        assert (
            listing(c, p, "motion_comic", candidate=True)["items"][0]["release_mode"]
            == "double_review"
        )
    with engine.begin() as c:
        raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM evidence_refs WHERE org_id=%s LIMIT 1", (p.org_id,)
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason,actor_member_id) VALUES (%s,%s,%s,1,'withdrawn','test',%s)",
            (uuid4(), p.org_id, raw, p.member_id),
        )
        assert listing(c, p, "motion_comic")["items"] == []


def test_legacy_import_cannot_be_used_by_application_role(engine, setup):
    import secrets

    from psycopg import sql
    from sqlalchemy.exc import DBAPIError

    from app.collection.service import insert
    from app.core.database import build_engine
    from app.core.database_roles import grant_application
    from app.knowledge.contracts import KnowledgeWrite, ManualSource
    from app.knowledge.legacy_import import import_rows, parse_quotes
    from app.knowledge.service import create
    from app.security.errors import Denied

    p = editor(engine, setup)
    role = "cip_legacy_test_" + uuid4().hex
    password = secrets.token_urlsafe(32)
    text = '## 二、共鸣金句库\n#### 男频 · 守护\n1. "守护。"\n## 三、18爽点内核库'
    with engine.begin() as c:
        cur = c.connection.driver_connection.cursor()
        cur.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
        grant_application(cur, role)
        item = create(
            c,
            p,
            uuid4(),
            KnowledgeWrite(
                title="已有资料",
                body_text="守护。",
                knowledge_type="content_atom",
                browse_category="quote",
                business_codes=["motion_comic"],
                manual_source=ManualSource(body_text="守护。", attribution="测试来源"),
            ),
        )
    limited = build_engine(engine.url.set(username=role, password=password))
    try:
        with pytest.raises(Denied, match="ACCESS_DENIED"), limited.begin() as c:
            import_rows(
                c,
                p,
                parse_quotes(text),
                source_text=text,
                source_name="K09.md",
                category="quote",
                reason="测试",
            )
        with (
            pytest.raises(DBAPIError, match="legacy import requires local database owner"),
            limited.begin() as c,
        ):
            insert(
                c,
                "knowledge_publications",
                p.org_id,
                knowledge_id=item["id"],
                revision_id=item["revision_id"],
                published_by=p.member_id,
                release_mode="legacy_import",
                import_metadata={
                    "source_sha256": "a" * 64,
                    "source_name": "test",
                    "source_code": "Q1",
                    "reason": "test",
                    "locations": [],
                },
            )
        with pytest.raises(DBAPIError, match="ck_publication_release_mode"), engine.begin() as c:
            insert(
                c,
                "knowledge_publications",
                p.org_id,
                knowledge_id=item["id"],
                revision_id=item["revision_id"],
                published_by=p.member_id,
            )
    finally:
        limited.dispose()
        with engine.begin() as c:
            cur = c.connection.driver_connection.cursor()
            cur.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_failure_import_preserves_body_sources_and_is_idempotent(engine, setup):
    from app.knowledge.legacy_import import import_rows, parse_failures
    from app.knowledge.service import listing

    p = editor(engine, setup)
    text = """# 模块10 · 41翻车点反模式手册
## 二、41翻车点完整清单
### 2.1 入口阶段翻车点
#### TP01 · 跳过分流直接立项
**描述**：保留描述。
**后果**：保留后果。
**修复**：保留修复。
## 三、`/anti_pattern` 命令规范"""
    rows = parse_failures(text)
    for expected in (1, 0):
        with engine.begin() as c:
            result = import_rows(
                c,
                p,
                rows,
                source_text=text,
                source_name="K08.md",
                category="failure",
                reason="用户确认已有翻车点直接导入",
            )
            assert result["created"] == expected
    with engine.begin() as c:
        item = listing(c, p, "motion_comic")["items"][0]
        assert item["browse_category"] == "failure"
        assert item["revision"]["body_text"] == rows[0]["body"]
        assert item["revision"]["knowledge_type"] == "method_rule"
        assert item["release_mode"] == "legacy_import"
        assert len(item["revision"]["evidence_ids"]) == 1
        assert listing(c, p, "story_short")["total"] == "1"
        assert listing(c, p, "ecommerce_video")["total"] == "0"
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM review_decisions WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )


def test_read_batch_memo_never_survives_source_withdrawal(engine, setup):
    from sqlalchemy import event

    from app.knowledge.legacy_import import import_rows, parse_quotes
    from app.security.errors import Denied
    from app.security.read_authorizer import ReadAuthorizer

    p = editor(engine, setup)
    text = '## 二、共鸣金句库\n#### 守护\n1. "守护。"\n## 三、18爽点内核库'
    with engine.begin() as c:
        kid = import_rows(
            c,
            p,
            parse_quotes(text),
            source_text=text,
            source_name="K09.md",
            category="quote",
            reason="fixture",
        )["ids"][0]
    from uuid import UUID

    kid = UUID(kid)
    statements = []

    def count(*args):
        statements.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        with engine.connect() as c:
            with c.begin():
                az = ReadAuthorizer(c, p)
                first = az.read("knowledge_items", kid)
                before = len(statements)
                assert az.read("knowledge_items", kid) == first
                assert len(statements) == before
                raw = c.exec_driver_sql(
                    "SELECT raw_asset_id FROM evidence_refs WHERE org_id=%s LIMIT 1", (p.org_id,)
                ).scalar_one()
            with c.begin():
                c.exec_driver_sql(
                    "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason,actor_member_id) VALUES (%s,%s,%s,1,'withdrawn','test',%s)",
                    (uuid4(), p.org_id, raw, p.member_id),
                )
            with c.begin(), pytest.raises(Denied):
                az.read("knowledge_items", kid)
    finally:
        event.remove(engine, "before_cursor_execute", count)


def test_payoff_import_is_idempotent_preserves_evidence_and_blocks_downgrade(engine, setup):
    from pathlib import Path
    from psycopg.errors import RaiseException
    from app.knowledge.legacy_import import import_rows, parse_payoffs
    from app.knowledge.service import listing

    p = editor(engine, setup)
    text = "### 3.1 18爽点完整清单\n1. 反杀爽：被欺压后强势反击\n### 3.2 v3.0四大案例爽点配置"
    rows = parse_payoffs(text)
    for expected in (1, 0):
        with engine.begin() as c:
            result = import_rows(
                c,
                p,
                rows,
                source_text=text,
                source_name="K09.md",
                category="payoff",
                reason="用户确认导入爽点",
            )
            assert result["created"] == expected
    with engine.begin() as c:
        item = listing(c, p, "motion_comic", category="payoff")["items"][0]
        assert item["title"] == "反杀爽"
        assert item["revision"]["body_text"] == "反杀爽：被欺压后强势反击"
        assert item["release_mode"] == "legacy_import"
        assert item["tags"][0] == {"kind": "stage", "code": "script"}
        assert len(item["revision"]["evidence_ids"]) == 1
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM review_decisions WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
    with (
        pytest.raises(RaiseException, match="Cannot downgrade while legacy payoff"),
        engine.begin() as c,
    ):
        cur = c.connection.driver_connection.cursor()
        cur.execute(Path("migrations/sql/0022_down.sql").read_text(), prepare=False)
