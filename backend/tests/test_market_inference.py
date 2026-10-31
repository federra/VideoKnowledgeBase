from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.topics import score_model, scoring
from app.topics.score_contracts import AssessmentView
from tests.test_topic_scoring import result


def inferred():
    body = result()
    for d in body["dimensions"][5:]:
        d.update(score=4, analysis="根据创作定位推断，受众和投放效果仍不确定")
    return body


def test_default_validator_preserves_inferred_market_and_computes_totals():
    body = inferred()
    original = deepcopy(body)
    value = score_model.validate_score(body)
    assert value["market_total"] == 20
    assert value["total"] == 35
    assert body == original


@pytest.mark.parametrize("bad", [True, "3", 3.0, -1, 6])
def test_market_scores_are_strict_integers(bad):
    body = inferred()
    body["dimensions"][5]["score"] = bad
    with pytest.raises(ValueError):
        score_model.validate_score(body)


def test_one_unknown_does_not_become_zero():
    body = inferred()
    body["dimensions"][5]["score"] = None
    value = score_model.validate_score(body)
    assert value["content_total"] == 15
    assert value["market_total"] is None and value["total"] is None


def test_legacy_handler_and_validator_remain_frozen():
    assert scoring.Score.version == "2"
    assert scoring.Score.rubric == "genre-load-v3-inferred"
    old = scoring.LegacyScore()
    assert old.version == "1" and old.rubric == "genre-load-v2"
    value = old.validator(inferred())
    assert all(d["score"] is None for d in value["dimensions"][5:])
    assert score_model.MARKET_LIMITATION in value["limitations"]
    assert "必须null" in old.prompt()
    assert "推断" in scoring.Score.prompt() and "不编造" in scoring.Score.prompt()


@pytest.mark.parametrize(
    "rubric,basis", [("genre-load-v2", "unavailable"), ("genre-load-v3-inferred", "ai_inference")]
)
def test_assessment_basis_is_derived_from_frozen_rubric(rubric, basis):
    value = score_model.validate_score(result())
    view = AssessmentView(
        id=uuid4(), topic_version=1, rubric_version=rubric, created_at=datetime.now(UTC), **value
    )
    assert view.model_dump()["market_basis"] == basis
