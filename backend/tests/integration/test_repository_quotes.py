import json
from uuid import uuid4

import pytest

from app.knowledge.contracts import KnowledgeRevisionWrite
from app.knowledge.legacy_import import import_rows, parse_repository
from app.knowledge.service import listing, revise
from tests.integration.test_knowledge import editor

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_repository_import_fields_repeat_revision_and_tags(engine, setup):
    p = editor(engine, setup)
    text = json.dumps(
        {
            "project": "silver",
            "commit": "a" * 40,
            "records": [
                {
                    "id": "film",
                    "film": {"title": "测试影片"},
                    "tags": ["剧情", "希望"],
                    "lines": [
                        {"text": "希望。", "en": "Hope.", "character": "角色", "note": "非逐字台词"}
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )

    def run(c):
        return import_rows(
            c,
            p,
            parse_repository(json.loads(text)),
            source_text=text,
            source_name="https://github.com/shenlq1017/silver-lines/tree/" + "a" * 40,
            category="quote",
            reason="用户授权测试",
            source_kind="repository",
        )

    with engine.begin() as c:
        first = run(c)
        assert first["created"] == 2
        assert run(c)["created"] == 0
        rows = listing(c, p, "motion_comic")["items"]
        assert len(rows) == 2
        assert {r["revision"]["body_text"] for r in rows} == {"希望。", "Hope."}
        for r in rows:
            assert r["revision"]["source_text"] == "测试影片"
            assert r["revision"]["explanation"] == "角色"
            assert "非逐字台词" in r["revision"]["limitations"]
            assert r["release_mode"] == "legacy_import"
            assert {"kind": "genre", "code": "希望"} in r["tags"]
        item = rows[0]
        request = KnowledgeRevisionWrite(
            title=item["title"],
            body_text=item["revision"]["body_text"],
            knowledge_type="content_atom",
            browse_category="quote",
            business_codes=["motion_comic", "story_short"],
            source_text="新来源",
            explanation="新解释",
            evidence_ids=item["revision"]["evidence_ids"],
            expected_lock_version=item["lock_version"],
            revision_reason="来源修订需重新审核",
        )
        revise(c, p, uuid4(), item["id"], request)
        assert all(
            r["revision"]["source_text"] == "测试影片"
            for r in listing(c, p, "motion_comic")["items"]
        )
        assert (
            listing(c, p, "motion_comic", candidate=True)["items"][0]["revision"]["source_text"]
            == "新来源"
        )
        assert run(c)["created"] == 0
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM review_decisions WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )


def test_review_snapshot_contains_attribution(engine, setup):
    from app.knowledge.contracts import KnowledgeWrite, ManualSource
    from app.knowledge.service import create
    from app.knowledge.tasks import snapshot

    p = editor(engine, setup)
    with engine.begin() as c:
        item = create(
            c,
            p,
            uuid4(),
            KnowledgeWrite(
                title="待审",
                body_text="句子",
                knowledge_type="content_atom",
                browse_category="quote",
                business_codes=["motion_comic"],
                source_text="影片",
                explanation="角色",
                manual_source=ManualSource(body_text="原文句子", attribution="用户提供"),
            ),
        )
        v = (
            c.exec_driver_sql(
                "SELECT * FROM knowledge_revisions WHERE id=%s", (item["revision_id"],)
            )
            .mappings()
            .one()
        )
        payload, _ = snapshot(c, p, "review", {"purpose": "knowledge_release"}, v, [])
        assert payload["target"]["source_text"] == "影片"
        assert payload["target"]["explanation"] == "角色"


def test_knowledge_batch_checks_source_state_and_parents_once(engine, setup):
    from sqlalchemy import event

    from app.knowledge.legacy_import import parse_quotes

    p = editor(engine, setup)
    text = '## 二、共鸣金句库\n#### 守护\n1. "守护。"\n2. "归来。"\n## 三、18爽点内核库'
    with engine.begin() as c:
        import_rows(
            c,
            p,
            parse_quotes(text),
            source_text=text,
            source_name="K09.md",
            category="quote",
            reason="fixture",
        )
    sql = []

    def observe(_c, _cursor, statement, *_args):
        sql.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with engine.begin() as c:
            assert len(listing(c, p, "motion_comic")["items"]) == 2
        assert sum("FROM raw_asset_events" in s for s in sql) == 1
        assert sum("cip_graph_edges" in s for s in sql) == 1
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    with engine.begin() as c:
        raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM evidence_refs WHERE org_id=%s LIMIT 1", (p.org_id,)
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason,actor_member_id) VALUES (%s,%s,%s,1,'withdrawn','test',%s)",
            (uuid4(), p.org_id, raw, p.member_id),
        )
    with engine.begin() as c:
        assert len(listing(c, p, "motion_comic")["items"]) == 1
    with engine.begin() as c:
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason,actor_member_id) VALUES (%s,%s,%s,2,'availability_restored','test',%s)",
            (uuid4(), p.org_id, raw, p.member_id),
        )
    with engine.begin() as c:
        assert len(listing(c, p, "motion_comic")["items"]) == 2
