import pytest


def test_text_parsing_preserves_original_paragraph_numbers_and_missing_media():
    from app.processing.research import parse_text

    value = parse_text("第一行\n\n第三行\r\n第四行")
    assert [(x["number"], x["text"]) for x in value] == [
        (1, "第一行"),
        (3, "第三行"),
        (4, "第四行"),
    ]
    for text in ("   ", "\x00bad", "x" * 200001):
        with pytest.raises(ValueError):
            parse_text(text)


def test_audio_probe_local_decode_and_invalid_input():
    import io
    import wave

    from app.processing.media import probe_media

    body = io.BytesIO()
    with wave.open(body, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000)
    value = probe_media(body.getvalue(), "audio/wav")
    assert value["media_kind"] == "audio" and value["duration_ms"] == 1000
    from app.tasks.service import TaskError

    with pytest.raises(TaskError):
        probe_media(b"not audio", "audio/wav")


def test_dedicated_parse_queue_is_declared_and_dispatchable(monkeypatch):
    from uuid import uuid4

    from app.tasks.celery_app import app

    assert "research" in app.amqp.queues
    from app.research.worker import dispatch_parse, execute_parse

    assert "research" in {q.name for q in app.conf.task_queues}
    sent = []
    monkeypatch.setattr(execute_parse, "apply_async", lambda **kw: sent.append(kw))
    dispatch_parse(uuid4(), uuid4())
    assert sent[0]["queue"] == "research" and sent[0]["retry"] is False


def test_default_worker_can_recognize_dedicated_parse_messages():
    from app.tasks.celery_app import app

    assert "app.research.worker" in app.conf.include
