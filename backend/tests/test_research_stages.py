"""Approved rubric shape and material scope, with isolated text only."""

from uuid import uuid4

import pytest

from app.research.stage_model import validate_output


def sample(rules):
    return {
        "business_code": "motion_comic",
        "scope": "material",
        "outcome_exposure": "unknown",
        "segments": [
            {
                "id": "s1",
                "source_kind": "material_version",
                "source_id": str(uuid4()),
                "source_version": 1,
                "text": "隔离原始句。",
            }
        ],
        "missing_inputs": ["无视听素材"],
        "rubric": {"grading_rules": rules},
    }


def output():
    return {
        "result_state": "completed",
        "coverage": "partial",
        "limitations": ["仅隔离文本"],
        "grade": "A",
        "dimensions": [{"name": "文本表达", "state": "supported", "claim_keys": ["x"]}],
        "claims": [
            {
                "key": "x",
                "dimension": "文本表达",
                "finding": "原文支持的局部观察",
                "evidence": [{"segment_id": "s1", "quote": "隔离原始句。"}],
            }
        ],
    }


@pytest.mark.parametrize("rules", [True, "enabled", {"A": "only one boundary"}, {}])
def test_incomplete_or_boolean_rubric_cannot_enable_rating(rules):
    with pytest.raises(ValueError):
        validate_output("evaluate", sample(rules), output())


def test_explicit_four_grade_boundaries_allow_material_rating_but_not_synopsis():
    value = sample({g: "隔离测试规则，不是项目业务标准" for g in ("S", "A", "B", "C")})
    assert validate_output("evaluate", value, output())["output"]["grade"] == "A"
    value["scope"] = "synopsis"
    with pytest.raises(ValueError):
        validate_output("evaluate", value, output())
