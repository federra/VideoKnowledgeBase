"""Real topic output validation; no API or model calls."""

import pytest
from app.topics.contracts import GenerateRequest, TopicFields
from app.topics.model import validate_generation, system_prompt


def fields(title="离职那天，我被未来的自己拦住了"):
    return dict(
        title=title,
        audience="都市悬疑观众",
        logline="一名失业程序员发现未来自己正阻止他接受新工作。",
        character_settings="主角渴望安全感；未来的自己想掩盖一次错误。",
        global_rhythm="以异常来信开篇，调查揭开代价，结尾作出选择。",
    )


def test_five_topics_are_required_and_cannot_repeat_titles():
    value = {"topics": [fields(str(i)) for i in range(5)]}
    assert len(validate_generation(value, "batch")["topics"]) == 5
    with pytest.raises(ValueError):
        validate_generation({"topics": [fields()]}, "batch")
    value["topics"][1]["title"] = value["topics"][0]["title"]
    with pytest.raises(ValueError):
        validate_generation(value, "batch")


def test_brainstorm_returns_one_complete_topic_without_model_scores():
    assert validate_generation({"topics": [fields()]}, "brainstorm")["topics"][0]["title"]
    with pytest.raises(ValueError):
        validate_generation({"topics": [dict(fields(), score=50)]}, "brainstorm")
    with pytest.raises(ValueError):
        validate_generation({"topics": [fields(" ")]}, "brainstorm")


def test_generation_scope_and_spark_requirements():
    with pytest.raises(ValueError):
        GenerateRequest(business_code="ecommerce_video", mode="batch")
    with pytest.raises(ValueError):
        GenerateRequest(business_code="story_short", mode="brainstorm", spark_ids=[])
    with pytest.raises(ValueError):
        GenerateRequest(
            business_code="story_short",
            mode="batch",
            spark_ids=["00000000-0000-4000-8000-000000000001"],
        )
    assert GenerateRequest(business_code="motion_comic", mode="batch").mode == "batch"


def test_business_prompts_and_injection_boundary():
    a = system_prompt("motion_comic", "batch")
    b = system_prompt("story_short", "brainstorm")
    assert "80集" in a and "5" in a
    assert "80集" not in b and "1" in b
    assert "不可信" in a and "不得" in b
    assert "评分" in a


def test_normalized_fields_do_not_create_spurious_versions():
    assert TopicFields(**fields(" 标题 ")).title == "标题"
