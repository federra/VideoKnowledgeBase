"""New v2 review approval must validate sources and all five checks."""

from uuid import uuid4

import pytest


def sample():
    return {
        "business_code": "motion_comic",
        "scope": "material",
        "outcome_exposure": "unknown",
        "segments": [
            {
                "id": "e1",
                "source_kind": "material_version",
                "source_id": str(uuid4()),
                "source_version": 1,
                "text": "角色发现线索。",
            }
        ],
        "missing_inputs": ["视听未提供"],
        "target_revision": {"id": str(uuid4()), "version": 1, "sha256": "a" * 64},
        "comparison_complete": True,
        "comparisons": [],
    }


def output():
    return {
        "result_state": "completed",
        "coverage": "partial",
        "limitations": ["仅当前授权范围"],
        "claims": [
            {
                "key": "support",
                "dimension": "来源支持",
                "finding": "与引用一致",
                "evidence": [{"segment_id": "e1", "quote": "角色发现线索。"}],
            }
        ],
        "decision": "approved",
        "checks": [
            {
                "kind": k,
                "state": "supported",
                "reason": "已检查当前冻结资料",
                "claim_keys": ["support"],
            }
            for k in ["support", "completeness", "duplicate", "conflict", "applicability"]
        ],
    }


def test_v2_review_accepts_exact_supported_frozen_review():
    from app.knowledge.model import validate_output

    assert validate_output("review", sample(), output())["output"]["decision"] == "approved"


@pytest.mark.parametrize(
    "bad", ["missing_check", "duplicate_check", "bad_quote", "missing_comparison", "missing_target"]
)
def test_v2_review_rejects_incomplete_approval(bad):
    from app.knowledge.model import validate_output

    s = sample()
    body = output()
    if bad == "missing_check":
        body["checks"].pop()
    if bad == "duplicate_check":
        body["checks"][-1] = body["checks"][0]
    if bad == "bad_quote":
        body["claims"][0]["evidence"][0]["quote"] = "未提供的话"
    if bad == "missing_comparison":
        s["comparison_complete"] = False
    if bad == "missing_target":
        s["target_revision"] = None
    with pytest.raises(ValueError):
        validate_output("review", s, body)


@pytest.mark.parametrize("text", ["https://example.com/source", "   "])
def test_manual_source_requires_text_instead_of_only_link(text):
    from app.knowledge.contracts import ManualSource

    with pytest.raises(ValueError):
        ManualSource(body_text=text, attribution="出处")
