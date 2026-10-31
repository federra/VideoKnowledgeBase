from uuid import uuid4

import pytest

from app.knowledge.genre_explanations import validate_output


def test_exact_targets_and_chinese_sentence():
    a, b = str(uuid4()), str(uuid4())
    value = {
        "items": [
            {"revision_id": b, "explanation": "以边地军旅人物的成长与抉择推动故事。"},
            {"revision_id": a, "explanation": "围绕家庭关系中的信任冲突展开叙事。"},
        ]
    }
    result = validate_output(value, [a, b])
    assert [str(x["revision_id"]) for x in result["items"]] == [a, b]


@pytest.mark.parametrize(
    "text",
    ["", "只有标题", "First sentence.", "第一句。第二句。", "第一行\n第二行。", "字" * 181 + "。"],
)
def test_invalid_sentence_rejected(text):
    a = str(uuid4())
    with pytest.raises(ValueError):
        validate_output({"items": [{"revision_id": a, "explanation": text}]}, [a])


def test_duplicate_missing_unknown_targets_rejected():
    a, b = str(uuid4()), str(uuid4())
    with pytest.raises(ValueError):
        validate_output(
            {"items": [{"revision_id": a, "explanation": "围绕家庭冲突展开叙事。"}]}, [a, b]
        )
    with pytest.raises(ValueError):
        validate_output(
            {"items": [{"revision_id": b, "explanation": "围绕家庭冲突展开叙事。"}]}, [a]
        )
    with pytest.raises(ValueError):
        validate_output(
            {"items": [{"revision_id": a, "explanation": "围绕家庭冲突展开叙事。"}] * 2}, [a, b]
        )
