import copy
from uuid import uuid4

import pytest


def sample():
    from app.ai.research import ResearchInput

    return ResearchInput.model_validate(
        {
            "business_code": "motion_comic",
            "scope": "synopsis",
            "outcome_exposure": "observed",
            "segments": [
                {
                    "id": "p1",
                    "source_kind": "content_observation",
                    "source_id": str(uuid4()),
                    "source_version": 1,
                    "text": "小林隐瞒身份，与伙伴共同解决危机。",
                }
            ],
            "missing_inputs": ["完整剧本", "音视频", "评级标准", "发布条件"],
        }
    )


def breakdown():
    return {
        "result_state": "completed",
        "coverage": "partial",
        "limitations": ["仅简介"],
        "claims": [
            {
                "key": "c1",
                "dimension": "人物设计",
                "finding": "小林隐瞒身份",
                "evidence": [{"segment_id": "p1", "quote": "小林隐瞒身份"}],
            }
        ],
    }


def test_six_research_definitions_versioned_and_frozen():
    from app.ai.research import DEFINITIONS, freeze_input, inspect_output, system_prompt

    assert set(DEFINITIONS) == {"parse", "decompose", "evaluate", "predict", "extract", "review"}
    frozen = freeze_input("decompose", sample())
    assert len(frozen["sha256"]) == 64 and frozen["definition_version"] == "research.decompose.v1"
    assert "json" in system_prompt("decompose") and "不可信" in system_prompt("decompose")
    assert all(x.model_json_schema()["additionalProperties"] is False for x in DEFINITIONS.values())
    checked = inspect_output("decompose", sample(), breakdown())
    assert checked["output"]["coverage"] == "partial"
    assert checked["anchors"]["c1"][0]["start"] == 0


@pytest.mark.parametrize("case", ["unknown", "quote", "duplicate", "full", "empty", "extra"])
def test_research_rejects_invented_evidence_and_scope(case):
    from app.ai.research import inspect_output

    body = breakdown()
    if case == "unknown":
        body["claims"][0]["evidence"][0]["segment_id"] = "foreign"
    if case == "quote":
        body["claims"][0]["evidence"][0]["quote"] = "不存在的剧情"
    if case == "duplicate":
        body["claims"] *= 2
    if case == "full":
        body["coverage"] = "full"
    if case == "empty":
        body["claims"] = []
    if case == "extra":
        body["release_knowledge"] = True
    with pytest.raises(ValueError):
        inspect_output("decompose", sample(), body)


def test_research_grade_prediction_and_review_do_not_bypass_gates():
    from app.ai.research import inspect_output

    body = {
        "result_state": "insufficient_evidence",
        "coverage": "partial",
        "limitations": ["缺评级标准"],
        "claims": [],
        "grade": None,
        "dimensions": [],
    }
    inspect_output("evaluate", sample(), body)
    body["grade"] = "A"
    with pytest.raises(ValueError):
        inspect_output("evaluate", sample(), body)
    prediction = {
        "result_state": "insufficient_evidence",
        "coverage": "partial",
        "limitations": ["历史简介，不可可靠预测"],
        "claims": [],
        "metric_code": None,
        "window_seconds": None,
        "lower_bound": None,
        "upper_bound": None,
        "uncertainty_note": "缺发布条件和独立校准样本",
    }
    inspect_output("predict", sample(), prediction)
    prediction.update(
        result_state="completed",
        metric_code="play_vv",
        window_seconds=86400,
        lower_bound="10",
        upper_bound="100",
    )
    with pytest.raises(ValueError):
        inspect_output("predict", sample(), prediction)
    review = {
        "result_state": "insufficient_evidence",
        "coverage": "partial",
        "limitations": ["无候选版本"],
        "claims": [],
        "decision": "insufficient_evidence",
        "checks": [],
    }
    inspect_output("review", sample(), review)
    review["decision"] = "approved"
    with pytest.raises(ValueError):
        inspect_output("review", sample(), review)


def test_research_input_rejects_blank_duplicate_and_fake_versions():
    from app.ai.research import ResearchInput

    data = sample().model_dump(mode="json")
    for change in ("blank", "duplicate", "version"):
        value = copy.deepcopy(data)
        if change == "blank":
            value["segments"][0]["text"] = "  "
        if change == "duplicate":
            value["segments"] *= 2
        if change == "version":
            value["segments"][0]["source_version"] = 0
        with pytest.raises(ValueError):
            ResearchInput.model_validate(value)


def test_six_task_payloads_and_candidate_classification():
    from app.ai.research import inspect_output

    value = sample()
    parsed = breakdown()
    parsed["detected_kind"] = "text"
    inspect_output("parse", value, parsed)
    parsed["claims"][0]["finding"] = "改写文本"
    with pytest.raises(ValueError):
        inspect_output("parse", value, parsed)
    extracted = breakdown()
    extracted["candidates"] = [
        {
            "title": "身份隐瞒案例",
            "body": "简介中小林隐瞒身份",
            "knowledge_type": "content_atom",
            "browse_category": "dna_case",
            "applicability": ["motion_comic"],
            "limitations": "单条简介，效果未经验证",
            "claim_keys": ["c1"],
            "status": "pending_ai_review",
        }
    ]
    inspect_output("extract", value, extracted)
    extracted["candidates"][0]["knowledge_type"] = "method_rule"
    with pytest.raises(ValueError):
        inspect_output("extract", value, extracted)
