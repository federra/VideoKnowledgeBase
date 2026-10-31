from uuid import uuid4

import pytest

from app.ai.feedback_v3 import inspect_batch


def test_exact_members_and_cross_work_reference_rejected():
    a, b, c, d = [str(uuid4()) for _ in range(4)]
    samples = [{"entry_id": a, "comments": [{"id": c}]}, {"entry_id": b, "comments": [{"id": d}]}]

    def result(cid):
        return {
            "result_state": "completed",
            "summary": "小样本",
            "claims": [
                {
                    "kind": "emotion",
                    "claim_key": "e",
                    "text": "期待",
                    "trigger": "后续",
                    "sentiment": "positive",
                    "comment_ids": [cid],
                }
            ],
        }

    body = {"items": [{"entry_id": b, "result": result(d)}, {"entry_id": a, "result": result(c)}]}
    assert [x["entry_id"] for x in inspect_batch(samples, body)["items"]] == [a, b]
    body["items"][0]["result"] = result(c)
    with pytest.raises(ValueError):
        inspect_batch(samples, body)
    with pytest.raises(ValueError):
        inspect_batch(samples, {"items": [body["items"][1]]})


def test_main_registry_includes_both_feedback_versions():
    from app.intelligence.feedback_v3 import FeedbackV3
    from app.tasks.handlers import registry

    handlers = registry()
    assert isinstance(handlers[("audience.feedback", "3")], FeedbackV3)
    assert ("audience.feedback", "2") in handlers
