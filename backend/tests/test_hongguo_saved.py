"""Authorized saved HTTP evidence must validate before any database mutation."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.tasks.service import TaskError
from tests.test_hongguo import html


def capture(body):
    now = datetime.now(UTC).isoformat()
    sha = hashlib.sha256(body.encode()).hexdigest()
    return {
        "url": "https://hongguoduanju.com/rank/hot-drama",
        "http_status": 200,
        "captured_at": now,
        "requested_at": now,
        "sha256": sha,
        "body_sha256": sha,
        "body_representation": "httpx_decoded_bytes",
        "saved_bytes": len(body.encode()),
        "received_bytes": len(body.encode()),
        "body_complete": True,
        "text_available": True,
        "content_type": "text/html",
        "content_encoding": "identity",
        "collection_job_id": None,
        "failure_kind": None,
        "failure_stage": None,
        "exception_type": None,
    }


def test_saved_capture_validates_original_time_sha_and_twenty_items():
    from app.collection.hongguo_saved import validate_capture

    body = html()
    meta = capture(body)
    moment = validate_capture(body, meta, "hot-drama")
    assert moment.isoformat() == meta["captured_at"]


@pytest.mark.parametrize(
    "change",
    [
        {"http_status": 403},
        {"body_complete": False},
        {"text_available": False},
        {"url": "https://other.example/rank/hot-drama"},
        {"sha256": "0" * 64},
        {"saved_bytes": 0},
        {"body_sha256": "0" * 64},
        {"collection_job_id": "old-job"},
        {"captured_at": "2020-01-01T00:00:00+00:00"},
        {"captured_at": "2026-10-26"},
        {"captured_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        {"failure_kind": "transfer_error"},
        {"content_type": "application/json"},
    ],
)
def test_saved_capture_rejects_wrong_or_incomplete_provenance(change):
    from app.collection.hongguo_saved import validate_capture

    body = html()
    with pytest.raises(TaskError, match="INVALID_INPUT"):
        validate_capture(body, {**capture(body), **change}, "hot-drama")


def test_saved_capture_rejects_wrong_board_and_more_than_twenty_cards():
    from app.collection.hongguo_saved import validate_capture

    body = html(count=21)
    with pytest.raises(TaskError, match="INVALID_INPUT"):
        validate_capture(body, capture(body), "hot-drama")
    body = html()
    with pytest.raises(TaskError, match="INVALID_INPUT"):
        validate_capture(body, capture(body), "hot-ai-drama")


def test_saved_capture_nul_roundtrip_is_jsonb_compatible_and_sha_checked():
    import json

    from app.collection.hongguo_saved import encode_saved, saved_html

    body = html(count=1) + "\x00"
    encoded = encode_saved(body, capture(body))
    # PostgreSQL jsonb cannot decode \u0000 into TEXT. Base64 preserves exact source bytes.
    assert "\\u0000" not in encoded and "\x00" not in encoded
    assert saved_html(encoded) == body
    envelope = json.loads(encoded)
    envelope["html_base64"] = "eA=="
    with pytest.raises(TaskError, match="INVALID_INPUT"):
        saved_html(json.dumps(envelope))
