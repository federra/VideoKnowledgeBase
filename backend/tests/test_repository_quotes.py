"""Source mapping and bilingual import are tested without a network dependency."""

from app.knowledge import legacy_import


def test_repository_quote_mapping_and_languages():
    parse = getattr(legacy_import, "parse_repository", None)
    assert parse is not None, "Repository quote parser is required"
    rows = parse(
        {
            "project": "golden",
            "commit": "a" * 40,
            "records": [
                {
                    "id": "g1",
                    "text": "前进。",
                    "author": "作者",
                    "tag": "游戏",
                    "date": "2026-01-01",
                }
            ],
        }
    )
    assert rows[0]["line"] == "A"
    assert rows[0]["explanation"] == "作者"
    assert rows[0]["tags"] == ["游戏"]
    rows = parse(
        {
            "project": "silver",
            "commit": "b" * 40,
            "records": [
                {
                    "id": "film",
                    "film": {"title": "影片"},
                    "tags": ["剧情"],
                    "lines": [
                        {"text": "希望。", "en": "Hope.", "character": "角色", "note": "非逐字台词"}
                    ],
                }
            ],
        }
    )
    assert [r["line"] for r in rows] == ["A", "B"]
    assert [r["text"] for r in rows] == ["希望。", "Hope."]
    assert all(
        r["source_text"] == "影片" and r["explanation"] == "角色" and r["note"] == "非逐字台词"
        for r in rows
    )
    assert len({r["code"] for r in rows}) == 2


def test_knowledge_optional_fields_contract():
    from app.knowledge.contracts import KnowledgeWrite

    request = KnowledgeWrite(
        title="知识",
        body_text="正文",
        knowledge_type="content_atom",
        browse_category="quote",
        business_codes=["motion_comic"],
        source_text="电影",
        explanation="角色",
    )
    assert request.source_text == "电影" and request.explanation == "角色"


def test_optional_metadata_does_not_change_legacy_idempotency_payload():
    from app.knowledge import service
    from app.knowledge.contracts import KnowledgeWrite

    req = KnowledgeWrite(
        title="旧知识",
        body_text="正文",
        knowledge_type="content_atom",
        browse_category="quote",
        business_codes=["motion_comic"],
    )
    method = getattr(service, "write_payload", None)
    assert method is not None
    assert method(req) == req.model_dump(mode="json", exclude={"source_text", "explanation"})
    assert method(req.model_copy(update={"source_text": "影片"}))["source_text"] == "影片"


def test_repository_parser_is_independent_of_json_key_order():
    import json

    source = {
        "project": "golden",
        "commit": "a" * 40,
        "records": [{"id": "g", "text": "原文", "author": "人物", "tag": "标签"}],
    }
    assert legacy_import.parse_repository(source) == legacy_import.parse_repository(
        json.loads(json.dumps(source, sort_keys=True))
    )


def test_knowledge_bulk_read_limit_is_bounded_and_other_lists_keep_small_limit():
    import pytest
    from pydantic import ValidationError

    from app.contracts.api import BusinessQuery, KnowledgeQuery

    assert KnowledgeQuery(business_code="motion_comic", limit=5000).limit == 5000
    with pytest.raises(ValidationError):
        KnowledgeQuery(business_code="motion_comic", limit=5001)
    with pytest.raises(ValidationError):
        BusinessQuery(business_code="motion_comic", limit=101)
