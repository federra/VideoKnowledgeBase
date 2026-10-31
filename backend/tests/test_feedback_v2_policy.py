from uuid import uuid4

import pytest

from app.ai.feedback_v2 import inspect_output


def test_unclassifiable_excluded_and_every_comment_covered():
    a, b = str(uuid4()), str(uuid4())
    sample = {"comments": [{"id": a}, {"id": b}]}
    claims = [
        {
            "kind": "emotion",
            "claim_key": "a",
            "text": "喜欢",
            "trigger": "喜欢",
            "sentiment": "positive",
            "comment_ids": [a],
        },
        {
            "kind": "emotion",
            "claim_key": "b",
            "text": "无法判断",
            "trigger": "无关广告",
            "sentiment": "unclassifiable",
            "comment_ids": [b],
        },
    ]
    checked = inspect_output(
        sample, {"result_state": "completed", "summary": "小样本", "claims": claims}
    )
    assert checked["classified_count"] == 1
    assert checked["emotions"] == [{"name": "喜欢", "count": 1, "percent": 100}]
    with pytest.raises(ValueError):
        inspect_output(
            sample, {"result_state": "completed", "summary": "小样本", "claims": claims[:1]}
        )
    claims.append({**claims[0], "claim_key": "c", "sentiment": "negative"})
    with pytest.raises(ValueError):
        inspect_output(sample, {"result_state": "completed", "summary": "小样本", "claims": claims})


def test_insufficient_only_unclassifiable():
    a = str(uuid4())
    claim = {
        "kind": "emotion",
        "claim_key": "a",
        "text": "无法判断",
        "trigger": "无关",
        "sentiment": "unclassifiable",
        "comment_ids": [a],
    }
    assert (
        inspect_output(
            {"comments": [{"id": a}]},
            {"result_state": "insufficient_evidence", "summary": None, "claims": [claim]},
        )["classified_count"]
        == 0
    )


def test_identity_and_context_change_sample_key():
    from app.intelligence.feedback_v2 import sample_key

    original = {
        "entry_id": "entry-a",
        "snapshot_id": "snapshot-a",
        "business_date": "2026-10-31",
        "platform_code": "hongguo",
        "comments": [{"id": "comment-a", "body_text": "喜欢"}],
    }
    baseline = sample_key(original)
    for name, value in [
        ("entry_id", "entry-b"),
        ("snapshot_id", "snapshot-b"),
        ("business_date", "2026-10-30"),
        ("platform_code", "douyin"),
        ("comments", [{"id": "comment-b", "body_text": "喜欢"}]),
    ]:
        assert sample_key({**original, name: value}) != baseline


def test_foreign_comment_id_and_insufficient_summary_rejected():
    a, b = str(uuid4()), str(uuid4())
    claim = {
        "kind": "emotion",
        "claim_key": "x",
        "text": "无法判断",
        "trigger": "无关",
        "sentiment": "unclassifiable",
        "comment_ids": [b],
    }
    with pytest.raises(ValueError):
        inspect_output(
            {"comments": [{"id": a}]},
            {"result_state": "insufficient_evidence", "summary": None, "claims": [claim]},
        )
    claim["comment_ids"] = [a]
    with pytest.raises(ValueError):
        inspect_output(
            {"comments": [{"id": a}]},
            {"result_state": "insufficient_evidence", "summary": "捏造总结", "claims": [claim]},
        )
