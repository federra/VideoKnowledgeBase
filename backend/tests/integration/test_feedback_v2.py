"""Isolated PostgreSQL, mocked configured transport; never collect or call a model."""

from uuid import UUID, uuid4

import pytest

from app.intelligence import feedback_v2 as f
from app.intelligence.feedback import entry_feedback
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.tasks.service import Runner
from tests.integration.test_collection import prepared, task_id
from tests.integration.test_schema import raw
from tests.integration.test_security import grant
from tests.integration.test_topics import configured, handler_for

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def fixture(engine, setup, monkeypatch, tmp_path):
    runner, start, org, member, *_ = prepared(engine, setup)
    assert runner.run(org, task_id(start())) == "succeeded"
    p = configured(engine, setup, monkeypatch)
    with engine.begin() as c:
        grant(c, org, member, member, ["research.run", "file.read"])
        _snap, entry, content, day = c.exec_driver_sql(
            "SELECT s.id,e.id,o.content_id,s.business_date FROM intelligence_snapshots s JOIN snapshot_entries e ON e.snapshot_id=s.id JOIN content_observations o ON o.id=e.content_observation_id WHERE s.org_id=%s",
            (org,),
        ).one()
        rid = raw(c, org, member, "synthetic original comment")
        cid = uuid4()
        c.exec_driver_sql(
            "INSERT INTO comment_evidence(id,org_id,content_id,raw_asset_id,platform_comment_id,body_text,like_count,captured_at,sample_position) VALUES(%s,%s,%s,%s,'comment-1','喜欢人物',2,clock_timestamp(),0)",
            (cid, org, content, rid),
        )
        comment = dict(
            c.exec_driver_sql(
                "SELECT * FROM comment_evidence WHERE org_id=%s AND id=%s", (org, cid)
            )
            .mappings()
            .one()
        )
        from app.model_config import resolve

        cfg = resolve(c, p, "motion_comic", "topic")
    monkeypatch.setattr(f, "resolve", lambda *args: cfg)

    def captured(c, p, snapshot, content):
        Authorizer(c, p).read("raw_assets", rid)
        return [
            {
                k: comment[k]
                for k in (
                    "id",
                    "created_at",
                    "content_id",
                    "platform_comment_id",
                    "body_text",
                    "like_count",
                    "username",
                    "posted_at_raw",
                    "posted_at",
                    "captured_at",
                )
            }
        ]

    monkeypatch.setattr("app.intelligence.creator_samples.sample", captured)
    calls = []
    output = {
        "result_state": "completed",
        "summary": "小样本喜欢人物，不能代表全体观众。",
        "claims": [
            {
                "kind": "emotion",
                "claim_key": "e",
                "text": "喜欢",
                "trigger": "人物",
                "sentiment": "positive",
                "comment_ids": [str(cid)],
            }
        ],
    }
    template = handler_for(tmp_path, output, calls)
    handler = f.FeedbackV2(template.model, template.store)
    monkeypatch.setattr("app.storage.http.get_store", lambda: template.store)
    return p, entry, day, rid, handler, calls, output


def test_one_call_exact_sample_idempotence_and_raw_file_revocation(
    engine, setup, monkeypatch, tmp_path
):
    p, entry, day, rid, handler, calls, _ = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c:
        value = entry_feedback(c, p, entry, "motion_comic", day)
        key = value["sample_key"]
        task = f.start(c, p, entry, "motion_comic", day, key, key=uuid4())
        assert f.start(c, p, entry, "motion_comic", day, key, key=uuid4())["id"] == task["id"]
    runner = Runner(engine, {(f.KIND, f.VERSION): handler}, lease_seconds=720)
    assert runner.run(p.org_id, UUID(str(task["id"]))) == "succeeded"
    assert len(calls) == 1
    runner.run(p.org_id, UUID(str(task["id"])))
    assert len(calls) == 1
    with engine.begin() as c:
        ready = entry_feedback(c, p, entry, "motion_comic", day)
        assert ready["status"] == "ready" and ready["classified_count"] == 1
        assert f.start(c, p, entry, "motion_comic", day, key, key=uuid4())["id"] == task["id"]
        frozen_raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM tasks WHERE id=%s", (task["id"],)
        ).scalar_one()
        files = list(
            c.exec_driver_sql(
                "SELECT input_manifest_file_id,output_file_id FROM ai_executions WHERE task_id=%s",
                (task["id"],),
            ).one()
        )
        for fid in files:
            assert Authorizer(c, p).read("file_objects", fid)
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(%s,%s,%s,1,'withdrawn','test')",
            (uuid4(), p.org_id, rid),
        )
    for kind, ident in [("raw_assets", frozen_raw), *[("file_objects", x) for x in files]]:
        with engine.begin() as c, pytest.raises(Denied):
            Authorizer(c, p).read(kind, ident)


def test_invalid_evidence_failure_requires_explicit_retry(engine, setup, monkeypatch, tmp_path):
    p, entry, day, _rid, handler, calls, output = fixture(engine, setup, monkeypatch, tmp_path)
    output["claims"][0]["comment_ids"] = [str(uuid4())]
    with engine.begin() as c:
        key = entry_feedback(c, p, entry, "motion_comic", day)["sample_key"]
        task = f.start(c, p, entry, "motion_comic", day, key, key=uuid4())
    assert (
        Runner(engine, {(f.KIND, f.VERSION): handler}, lease_seconds=720).run(
            p.org_id, UUID(str(task["id"]))
        )
        == "failed"
    )
    with engine.begin() as c, pytest.raises(Denied):
        f.start(c, p, entry, "motion_comic", day, key, key=uuid4())
    with engine.begin() as c:
        retry = f.start(
            c, p, entry, "motion_comic", day, key, key=uuid4(), retry_of=UUID(str(task["id"]))
        )
        assert retry["id"] != task["id"]
        assert f.analysis(c, p, UUID(str(task["id"])))["state"] == "failed"
    assert len(calls) == 1


def test_wrong_sample_and_unconfigured_zero_calls(engine, setup, monkeypatch, tmp_path):
    p, entry, day, _rid, _handler, calls, _ = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c, pytest.raises(Denied, match="VERSION_CONFLICT"):
        f.start(c, p, entry, "motion_comic", day, "0" * 64, key=uuid4())

    def unconfigured(*args):
        raise Denied("MODEL_NOT_CONFIGURED")

    monkeypatch.setattr(f, "resolve", unconfigured)
    with engine.begin() as c:
        value = entry_feedback(c, p, entry, "motion_comic", day)
        assert not value["analysis_model_ready"]
        with pytest.raises(Denied, match="MODEL_NOT_CONFIGURED"):
            f.start(c, p, entry, "motion_comic", day, value["sample_key"], key=uuid4())
    assert not calls


def test_insufficient_saved_without_invented_summary(engine, setup, monkeypatch, tmp_path):
    p, entry, day, _rid, handler, calls, output = fixture(engine, setup, monkeypatch, tmp_path)
    output.update(result_state="insufficient_evidence", summary=None)
    output["claims"][0].update(sentiment="unclassifiable", text="无法判断", trigger="语义不明")
    with engine.begin() as c:
        key = entry_feedback(c, p, entry, "motion_comic", day)["sample_key"]
        task = f.start(c, p, entry, "motion_comic", day, key, key=uuid4())
    assert (
        Runner(engine, {(f.KIND, f.VERSION): handler}, lease_seconds=720).run(
            p.org_id, UUID(task["id"])
        )
        == "succeeded"
    )
    with engine.begin() as c:
        value = entry_feedback(c, p, entry, "motion_comic", day)
        assert value["classified_count"] == 0 and value["summary"] is None
        assert value["analysis"]["result_state"] == "insufficient_evidence"
    assert len(calls) == 1


def test_changed_configuration_fails_before_reserving_call(engine, setup, monkeypatch, tmp_path):
    p, entry, day, _rid, handler, calls, _ = fixture(engine, setup, monkeypatch, tmp_path)
    with engine.begin() as c:
        key = entry_feedback(c, p, entry, "motion_comic", day)["sample_key"]
        task = f.start(c, p, entry, "motion_comic", day, key, key=uuid4())
    original = f.resolve
    monkeypatch.setattr(
        f, "resolve", lambda *args: {**original(*args), "binding_lock_version": "999"}
    )
    assert (
        Runner(engine, {(f.KIND, f.VERSION): handler}, lease_seconds=720).run(
            p.org_id, UUID(task["id"])
        )
        == "failed"
    )
    assert not calls


def test_real_legacy_fallback_v2_publish_keeps_old_report_and_other_work(
    engine, setup, monkeypatch, tmp_path
):
    """No creator helper shortcut: two works share the actual sealed v1 fallback."""
    import httpx

    from app.ai.feedback_task import private_file
    from app.collection.service import insert
    from app.core.models import metadata
    from app.core.repository import claim_task, create_task, finish_task
    from app.intelligence.feedback import read_feedback
    from app.intelligence.service import feed
    from app.model_config import resolve
    from tests.integration.test_collection import payload

    body = payload()
    body["data"]["list"].append(
        {
            **body["data"]["list"][0],
            "videoId": "second-work",
            "opusUrl": "https://www.douyin.com/video/456",
        }
    )
    collector, _start, org, member, source, _, collection_request, _, token = prepared(
        engine, setup, response=lambda _: httpx.Response(200, json=body)
    )
    from app.collection.service import submit as submit_collection
    from app.security.sessions import authenticate

    with engine.begin() as c:
        accepted = submit_collection(
            c,
            authenticate(c, token),
            collection_request.model_copy(update={"max_items": 2}),
            str(uuid4()),
            next(iter(collector.handlers.values())),
        )
    assert collector.run(org, task_id(accepted)) == "succeeded"
    p = configured(engine, setup, monkeypatch)
    monkeypatch.setattr("app.intelligence.creator_samples.sample", lambda *args: None)
    calls = []
    output = {"result_state": "completed", "summary": "第一作品小样本情绪。", "claims": []}
    template = handler_for(tmp_path, output, calls)
    handler = f.FeedbackV2(template.model, template.store)
    monkeypatch.setattr("app.storage.http.get_store", lambda: template.store)
    with engine.begin() as c:
        grant(c, org, member, member, ["research.run", "file.read"])
        cfg = resolve(c, p, "motion_comic", "topic")
        rows = (
            c.exec_driver_sql(
                "SELECT s.id snapshot,e.id entry,o.content_id,s.business_date FROM intelligence_snapshots s JOIN snapshot_entries e ON e.snapshot_id=s.id JOIN content_observations o ON o.id=e.content_observation_id WHERE s.org_id=%s ORDER BY e.id",
                (org,),
            )
            .mappings()
            .all()
        )
        assert len(rows) == 2
        snapshot, day = rows[0]["snapshot"], rows[0]["business_date"]
        raw_id = raw(c, org, member, "synthetic v1 original comments")
        legacy_task, _ = create_task(
            c,
            {
                "org_id": org,
                "kind": "audience.feedback",
                "handler_version": "1",
                "source_id": source,
                "business_code": "motion_comic",
                "requested_by": member,
                "execution_authorized_by": member,
                "idempotency_key": str(uuid4()),
                "input_sha256": "d" * 64,
                "max_external_calls": 1,
            },
            [
                {"role": "config", "ai_config_revision_id": cfg["revision_id"]},
                {"role": "material", "snapshot_id": snapshot},
                {"role": "comments", "raw_asset_id": raw_id},
            ],
        )
        attempt, token, version = claim_task(c, org, legacy_task, 2)
        legacy_row = (
            c.exec_driver_sql("SELECT * FROM tasks WHERE id=%s", (legacy_task,)).mappings().one()
        )
        file_id = private_file(c, handler.store, legacy_row, "{}")
        execution = insert(
            c,
            "ai_executions",
            org,
            task_id=legacy_task,
            attempt_id=attempt,
            config_revision_id=cfg["revision_id"],
            invocation_no=1,
            input_sha256="d" * 64,
            input_manifest_file_id=file_id,
        )
        c.exec_driver_sql(
            "UPDATE ai_executions SET result_state='completed',output_file_id=%s,finished_at=clock_timestamp() WHERE id=%s",
            (file_id, execution),
        )
        legacy = insert(
            c,
            "feedback_snapshots",
            org,
            snapshot_id=snapshot,
            version_no=1,
            task_id=legacy_task,
            ai_execution_id=execution,
            sampling_description="旧版同日评论样本",
            sample_count=2,
            classified_count=2,
            coverage_note="仅已保存样本",
            summary="原v1报告原文保持",
        )
        comment_ids = []
        for pos, row in enumerate(rows):
            comment = uuid4()
            comment_ids.append(comment)
            c.exec_driver_sql(
                "INSERT INTO comment_evidence(id,org_id,content_id,raw_asset_id,platform_comment_id,body_text,like_count,captured_at,sample_position) VALUES(%s,%s,%s,%s,%s,'期待下一集',1,clock_timestamp(),%s)",
                (comment, org, row["content_id"], raw_id, "legacy-" + str(pos), pos),
            )
            c.execute(
                metadata.tables["feedback_comments"]
                .insert()
                .values(org_id=org, feedback_id=legacy, comment_id=comment, position=pos)
            )
            claim = insert(
                c,
                "feedback_claims",
                org,
                feedback_id=legacy,
                kind="emotion",
                claim_key="legacy-" + str(pos),
                text="旧版期待" + str(pos),
                details={"trigger": "下一集"},
                support_count=1,
            )
            c.execute(
                metadata.tables["feedback_claim_evidence"]
                .insert()
                .values(org_id=org, feedback_id=legacy, claim_id=claim, comment_id=comment)
            )
        c.exec_driver_sql("SELECT cip_seal('feedback_snapshots',%s,%s)", (org, legacy))
        finish_task(c, org, legacy_task, attempt, token, version)
        legacy_before = read_feedback(c, p, legacy)
    monkeypatch.setattr(f, "resolve", lambda *args: cfg)
    entry = rows[0]["entry"]
    output["claims"] = [
        {
            "kind": "emotion",
            "claim_key": "v2",
            "text": "新版期待",
            "trigger": "下一集",
            "sentiment": "positive",
            "comment_ids": [str(comment_ids[0])],
        }
    ]
    with engine.begin() as c:
        old = entry_feedback(c, p, entry, "motion_comic", day)
        assert old["feedback_id"] == legacy and old["sample_count"] == 1
        task = f.start(c, p, entry, "motion_comic", day, old["sample_key"], key=uuid4())
    assert (
        Runner(engine, {(f.KIND, f.VERSION): handler}, lease_seconds=720).run(org, UUID(task["id"]))
        == "succeeded"
    )
    with engine.begin() as c:
        current = entry_feedback(c, p, entry, "motion_comic", day)
        assert current["status"] == "ready" and current["feedback_id"] != legacy
        assert current["claims"][0]["text"] == "新版期待"
        assert current["sample_key"] == old["sample_key"]
        assert read_feedback(c, p, legacy) == legacy_before
        other = entry_feedback(c, p, rows[1]["entry"], "motion_comic", day)
        assert other["feedback_id"] == legacy and other["claims"][0]["text"] == "旧版期待1"
        previews = {
            x["entry"]["id"]: x for x in feed(c, p, "motion_comic", day, "creator")["items"]
        }
        assert previews[entry]["feedback_emotions"] == ["新版期待"]
        assert previews[rows[1]["entry"]]["entry"]["feedback_id"] == legacy
        assert previews[rows[1]["entry"]]["feedback_emotions"] == ["旧版期待1"]
    assert len(calls) == 1


def test_hongguo_exact_v2_preview_only_analyzed_entry(engine, setup, monkeypatch, tmp_path):
    import httpx

    from app.collection.hongguo import CaptureHongguo, submit
    from app.connectors.hongguo import VERSION, Hongguo
    from app.intelligence.service import feed, shanghai_date
    from app.security.sessions import authenticate
    from tests.test_hongguo import html, player

    org, member, token, *_ = setup
    monkeypatch.setattr("app.connectors.hongguo.INTERVAL", 0)
    with engine.begin() as c:
        grant(
            c,
            org,
            member,
            member,
            [
                "source.configure",
                "collection.run",
                "content.read",
                "evidence.read",
                "research.run",
                "file.read",
            ],
        )
    http_calls = []

    def transport(request):
        http_calls.append(request.url.path)
        return httpx.Response(
            200, text=player() if request.url.path.startswith("/player/") else html(count=2)
        )

    capture = CaptureHongguo(
        Hongguo(httpx.Client(transport=httpx.MockTransport(transport)), tmp_path / "gate.json")
    )
    runner = Runner(engine, {("collect.hongguo", VERSION): capture})
    with engine.begin() as c:
        p = authenticate(c, token)
        board = submit(c, p, {"board": "hot-drama"}, capture)
    assert runner.run(org, UUID(board["task_id"])) == "succeeded"
    with engine.begin() as c:
        rows = feed(c, p, "motion_comic", shanghai_date(), video_catalog="hongguo")["items"]
        target = next(x for x in rows if x["entry"]["observation"]["platform_id"] == "1")
        content = c.exec_driver_sql(
            "SELECT id FROM external_contents WHERE org_id=%s AND platform_code='hongguo' AND platform_content_id='1'",
            (org,),
        ).scalar_one()
        comments = submit(
            c,
            p,
            {"series_id": "1"},
            capture,
            content_id=content,
            snapshot_id=target["entry"]["snapshot_id"],
        )
    assert runner.run(org, UUID(comments["task_id"])) == "succeeded"
    p = configured(engine, setup, monkeypatch)
    from app.model_config import resolve

    with engine.begin() as c:
        cfg = resolve(c, p, "motion_comic", "topic")
        before = entry_feedback(c, p, target["entry"]["id"], "motion_comic", shanghai_date())
    monkeypatch.setattr(f, "resolve", lambda *args: cfg)
    model_calls = []
    output = {
        "result_state": "completed",
        "summary": "仅当前播放页小样本。",
        "claims": [
            {
                "kind": "emotion",
                "claim_key": "all",
                "text": "样本期待",
                "trigger": "后续剧情",
                "sentiment": "positive",
                "comment_ids": [str(x["id"]) for x in before["comments"]],
            }
        ],
    }
    template = handler_for(tmp_path, output, model_calls)
    handler = f.FeedbackV2(template.model, template.store)
    monkeypatch.setattr("app.storage.http.get_store", lambda: template.store)
    with engine.begin() as c:
        task = f.start(
            c,
            p,
            target["entry"]["id"],
            "motion_comic",
            shanghai_date(),
            before["sample_key"],
            key=uuid4(),
        )
    requests_before = len(http_calls)
    assert (
        Runner(engine, {(f.KIND, f.VERSION): handler}, lease_seconds=720).run(org, UUID(task["id"]))
        == "succeeded"
    )
    with engine.begin() as c:
        from sqlalchemy import event

        from app.intelligence import hongguo as sample_reader

        canonical_calls = []
        queries = []
        original_sample = sample_reader.sample_for_content

        def counted_sample(*args, **kwargs):
            canonical_calls.append(1)
            return original_sample(*args, **kwargs)

        def query(*args):
            queries.append(1)

        monkeypatch.setattr(sample_reader, "sample_for_content", counted_sample)
        event.listen(engine, "before_cursor_execute", query)
        try:
            after = entry_feedback(c, p, target["entry"]["id"], "motion_comic", shanghai_date())
        finally:
            event.remove(engine, "before_cursor_execute", query)
        assert len(canonical_calls) == 1
        assert len(queries) < 150

        rows = feed(c, p, "motion_comic", shanghai_date(), video_catalog="hongguo")["items"]
        actual = next(x for x in rows if x["entry"]["id"] == target["entry"]["id"])
        other = next(x for x in rows if x["entry"]["id"] != target["entry"]["id"])
        assert str(actual["entry"]["feedback_id"]) == str(after["feedback_id"])
        assert actual["feedback_emotions"] == ["样本期待"]
        assert not other["entry"]["feedback_id"] and not other.get("feedback_emotions", [])
        assert "未执行AI分析" not in after["coverage_note"]
        assert after["sample_key"] == before["sample_key"]
    assert len(http_calls) == requests_before and len(model_calls) == 1
