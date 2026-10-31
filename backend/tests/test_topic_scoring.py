import pytest
from pydantic import ValidationError

from app.topics.score_model import KEYS, validate_legacy_score as validate_score


def result():
    return {
        "dimensions": [
            {
                "key": k,
                "score": 3 if i < 5 else None,
                "analysis": "文本依据" if i < 5 else "无市场证据",
            }
            for i, k in enumerate(KEYS)
        ],
        "limitations": ["仅文本评估"],
    }


def test_server_totals_unknown_market():
    value = validate_score(result())
    assert value["content_total"] == 15
    assert value["market_total"] is None and value["total"] is None


@pytest.mark.parametrize("invalid", [True, "3", 3.0, -1, 6])
def test_strict_integer_score(invalid):
    body = result()
    body["dimensions"][0]["score"] = invalid
    with pytest.raises((ValueError, ValidationError)):
        validate_score(body)


def test_market_claims_cannot_create_verified_scores():
    body = result()
    for d in body["dimensions"][5:]:
        d["score"] = 5
    value = validate_score(body)
    assert all(d["score"] is None for d in value["dimensions"][5:])
    assert value["total"] is None


def test_dimension_order_and_completeness_are_required():
    body = result()
    body["dimensions"].reverse()
    with pytest.raises(ValueError):
        validate_score(body)
    body = result()
    body["dimensions"].pop()
    with pytest.raises(ValueError):
        validate_score(body)


def test_missing_content_never_counts_as_zero():
    body = result()
    body["dimensions"][0]["score"] = None
    assert validate_score(body)["content_total"] is None
