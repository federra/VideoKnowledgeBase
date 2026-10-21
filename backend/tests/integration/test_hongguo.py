"""Real isolated PostgreSQL, bounded fake HTTP; no live source or business data."""

from uuid import UUID

import httpx
import pytest

from tests.integration.test_security import grant
from tests.test_hongguo import html, player

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_hongguo_offline_reparse_preserves_completed_failure(engine, setup, tmp_path, monkeypatch):
    from app.collection.hongguo import CaptureHongguo, submit
    from app.collection.hongguo_recovery import RecoverBoard, retain_and_submit
    from app.connectors import hongguo
    from app.connectors.redfox import AdapterError
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    org, member, token, *_ = setup
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            ["source.configure", "collection.run", "content.read", "evidence.read"],
        )
    monkeypatch.setattr(hongguo, "INTERVAL", 0)
    calls = []

    def transport(r):
        calls.append(r.url.path)
        return httpx.Response(200, text=html(count=1))

    handler = CaptureHongguo(
        hongguo.Hongguo(
            httpx.Client(transport=httpx.MockTransport(transport)), tmp_path / "gate.json"
        )
    )
    original = hongguo.normalize_board

    def old_parser(*args):
        raise AdapterError("INVALID_RESPONSE")

    monkeypatch.setattr(hongguo, "normalize_board", old_parser)
    with engine.begin() as c:
        saved = submit(c, authenticate(c, token), {"board": "hot-drama"}, handler)
    assert (
        Runner(engine, {("collect.hongguo", hongguo.VERSION): handler}).run(
            org, UUID(saved["task_id"])
        )
        == "failed"
    )
    monkeypatch.setattr(hongguo, "normalize_board", original)
    with engine.begin() as c:
        tid = retain_and_submit(
            c,
            authenticate(c, token),
            UUID(saved["job_id"]),
            next(tmp_path.glob("board-hot-drama-*.html")),
        )
    assert (
        Runner(engine, {("hongguo.recover", hongguo.VERSION): RecoverBoard()}).run(org, tid)
        == "succeeded"
    )
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT outcome FROM collection_calls WHERE job_id=%s", (UUID(saved["job_id"]),)
            ).scalar_one()
            == "invalid_shape"
        )
        assert (
            c.exec_driver_sql(
                "SELECT state FROM tasks WHERE id=%s", (UUID(saved["task_id"]),)
            ).scalar_one()
            == "failed"
        )
        assert (
            c.exec_driver_sql(
                "SELECT entry_count FROM intelligence_snapshots WHERE job_id=%s",
                (UUID(saved["job_id"]),),
            ).scalar_one()
            == 1
        )
    assert len(calls) == 1
    # Even another response under the SAME call/job cannot enter this exact reparse.
    import hashlib
    from uuid import uuid4

    from app.collection import hongguo_recovery
    from app.collection.service import insert
    from app.core.repository import create_task
    from app.security.authorization import Authorizer
    from app.tasks.service import input_digest

    with engine.begin() as c:
        raw = (
            c.exec_driver_sql(
                "SELECT * FROM raw_assets WHERE collection_job_id=%s", (UUID(saved["job_id"]),)
            )
            .mappings()
            .one()
        )
        other_body = raw["body_text"] + " "
        other_raw = insert(
            c,
            "raw_assets",
            org,
            origin="api",
            asset_kind="response",
            collection_job_id=raw["collection_job_id"],
            collection_call_id=raw["collection_call_id"],
            body_text=other_body,
            sha256=hashlib.sha256(other_body.encode()).hexdigest(),
            captured_at=raw["captured_at"],
        )
        p = authenticate(c, token)
        values = {
            "id": uuid4(),
            "org_id": org,
            "kind": "hongguo.recover",
            "handler_version": hongguo.VERSION,
            "source_id": UUID(saved["source_id"]),
            "business_code": "motion_comic",
            "requested_by": member,
            "execution_authorized_by": member,
            "max_external_calls": 0,
            "max_attempts": 1,
            "idempotency_key": str(uuid4()),
        }
        values["input_sha256"] = input_digest(
            values, RecoverBoard().freeze(c, values, Authorizer(c, p), raw_id=raw["id"])
        )
        create_task(c, values, [{"role": "captured_response", "raw_asset_id": raw["id"]}])
    actual_publish = hongguo_recovery.publish_batch

    def mixed(c, task, raw, job, batch, **kwargs):
        return actual_publish(c, task, {**raw, "id": other_raw}, job, batch, **kwargs)

    monkeypatch.setattr(hongguo_recovery, "publish_batch", mixed)
    assert (
        Runner(engine, {("hongguo.recover", hongguo.VERSION): RecoverBoard()}).run(
            org, values["id"]
        )
        == "failed"
    )
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM intelligence_snapshots WHERE job_id=%s",
                (UUID(saved["job_id"]),),
            ).scalar_one()
            == 1
        )


def test_hongguo_pipeline_sample_read_sort_scope_and_idempotency(
    engine, setup, tmp_path, monkeypatch
):
    from app.collection.hongguo import CaptureHongguo, submit
    from app.connectors.hongguo import VERSION, Hongguo
    from app.contracts.models import EntryFeedback, IntelligenceFeed
    from app.intelligence.feedback import entry_feedback
    from app.intelligence.service import feed, shanghai_date
    from app.security.sessions import authenticate
    from app.tasks.service import Runner

    monkeypatch.setattr("app.connectors.hongguo.INTERVAL", 0)
    org, member, token, *_ = setup
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            ["source.configure", "collection.run", "content.read", "evidence.read"],
        )
    calls = []

    def respond(req):
        calls.append(req.url.path)
        if req.url.path.startswith("/player/"):
            return httpx.Response(200, text=player())
        raw = html(count=2).replace("rank-title-2", "rank-title-2")
        # Numeric order differs from source position; all-board must sort before pagination.
        raw = raw.replace("8070万热度", "9.6万热度", 1)
        return httpx.Response(200, text=raw)

    handler = CaptureHongguo(
        Hongguo(httpx.Client(transport=httpx.MockTransport(respond)), tmp_path / "gate.json")
    )
    runner = Runner(engine, {("collect.hongguo", VERSION): handler})
    with engine.begin() as c:
        p = authenticate(c, token)
        board = submit(c, p, {"board": "hot-drama"}, handler)
    assert runner.run(org, UUID(board["task_id"])) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, token)
        assert submit(c, p, {"board": "hot-drama"}, handler) == board
        result = feed(c, p, "motion_comic", shanghai_date(), video_catalog="hongguo")
        IntelligenceFeed.model_validate(result)
        assert result["total"] == "2"
        assert [v["entry"]["observation"]["platform_id"] for v in result["items"]] == ["2", "1"]
        assert result["video_genres"] == ["脑洞"] and result["video_subgenres"] == ["逆袭"]
        assert (
            feed(
                c,
                p,
                "motion_comic",
                shanghai_date(),
                video_catalog="hongguo",
                video_subgenre="异能",
            )["total"]
            == "0"
        )
        assert (
            feed(
                c,
                p,
                "motion_comic",
                shanghai_date(),
                video_catalog="hongguo",
                video_board="hot-ai-drama",
            )["total"]
            == "0"
        )
        assert feed(c, p, "motion_comic", shanghai_date())["total"] == "0"
        content = c.exec_driver_sql(
            "SELECT id FROM external_contents WHERE org_id=%s AND platform_code='hongguo' AND platform_content_id='1'",
            (org,),
        ).scalar_one()
        entry = result["items"][1]["entry"]
        sample = submit(
            c, p, {"series_id": "1"}, handler, content_id=content, snapshot_id=entry["snapshot_id"]
        )
    assert runner.run(org, UUID(sample["task_id"])) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, token)
        data = entry_feedback(c, p, entry["id"], "motion_comic", shanghai_date())
        EntryFeedback.model_validate(data)
        assert data["status"] == "sampled" and data["sample_count"] == 15
        assert data["classified_count"] == 0 and not data["claims"] and data["feedback_id"] is None
        assert data["comments"][0]["platform_comment_id"] is None
        assert (
            feed(c, p, "motion_comic", shanghai_date(), video_catalog="hongguo")["items"][1][
                "comment_sample_count"
            ]
            == 15
        )
        assert (
            submit(
                c,
                p,
                {"series_id": "1"},
                handler,
                content_id=content,
                snapshot_id=entry["snapshot_id"],
            )
            == sample
        )
        raw = c.exec_driver_sql(
            "SELECT id FROM raw_assets WHERE org_id=%s AND collection_job_id=%s",
            (org, UUID(sample["job_id"])),
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES (gen_random_uuid(),%s,%s,1,'access_revoked','test')",
            (org, raw),
        )
        assert (
            entry_feedback(c, p, entry["id"], "motion_comic", shanghai_date())["status"]
            == "not_acquired"
        )
    assert len(calls) == 2
