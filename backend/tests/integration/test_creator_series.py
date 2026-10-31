from uuid import UUID, uuid4

import pytest

from app.intelligence.creator_contracts import CreatorBatch
from app.intelligence.creators import save
from app.intelligence.refresh import start
from app.intelligence.refresh_worker import runtime
from app.security.sessions import authenticate
from tests.integration.test_feed_refresh import authorize
from tests.test_douyin_series import page, series

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


@pytest.mark.parametrize(
    "mode", ["complete", "blocked", "reparse", "browser", "browser_fetch_failure"]
)
def test_free_complete_catalog_snapshot_comments_and_no_other_channels(
    engine, setup, monkeypatch, tmp_path, mode
):
    import httpx

    from app.connectors.douyin_public_http import PublicDouyin
    from app.intelligence import creator_series
    from app.intelligence.service import feed, shanghai_date

    monkeypatch.setattr("app.intelligence.creator_resolution.PROFILE_INTERVAL", 0)
    authorize(engine, setup)
    calls = []
    browser = mode.startswith("browser")

    def http(request):
        assert not request.headers.get("cookie")
        assert request.url.host == "www.douyin.com"
        calls.append(request.url.path)
        if request.url.path.endswith("series/list/"):
            return httpx.Response(
                200,
                json=page(
                    [series(999, 326000), *([series(998, 90000)] if browser else [])],
                    20,
                    1,
                )
                if request.url.params.get("cursor") == "0"
                else page([]),
            )
        if request.url.path.endswith("series/aweme/"):
            if mode != "complete":
                return httpx.Response(200, text="blocked")
            return httpx.Response(
                200,
                json={
                    "status_code": 0,
                    "aweme_list": [
                        {
                            "aweme_id": "111",
                            "series_info": {"series_id": "999"},
                            "author": {"uid": "123456"},
                            "series_play_info": {"series_aweme_index": 1},
                        }
                    ],
                },
            )
        assert request.url.path.endswith("comment/list/")
        return httpx.Response(
            200,
            json={
                "status_code": 0,
                "comments": [
                    {
                        "cid": "123",
                        "aweme_id": "111",
                        "text": "真实测试结构",
                        "create_time": 1700000000,
                        "digg_count": 5,
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(http))
    monkeypatch.setattr(creator_series, "PublicDouyin", lambda: PublicDouyin(client, tmp_path))
    monkeypatch.setattr("app.connectors.douyin_public_http.time.sleep", lambda *_: None)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        save(
            c,
            p,
            CreatorBatch(
                business_code="motion_comic", links="https://www.douyin.com/user/MS4w_test"
            ),
            str(uuid4()),
        )
        batch = start(c, p, "motion_comic", str(uuid4()), creators_only=True)
    from app.collection.creator_series import CreatorSeries

    original_execute = CreatorSeries.execute_ticket
    if mode == "reparse":

        def old_failure(self, *args):
            result = original_execute(self, *args)
            assert result["unavailable"]
            from app.tasks.service import TaskError

            raise TaskError("INVALID_RESPONSE")

        monkeypatch.setattr(CreatorSeries, "execute_ticket", old_failure)
    assert runtime(engine).run(setup[0], UUID(batch["task_id"])) == "succeeded"
    if mode == "reparse":
        monkeypatch.setattr(CreatorSeries, "execute_ticket", original_execute)
        from app.collection.creator_reparse import reparse_batch
        from app.security.sessions import MemberPrincipal

        ids = reparse_batch(engine, MemberPrincipal(p.org_id, p.member_id), UUID(batch["task_id"]))
        assert len(ids) == 1

    with engine.begin() as c:
        p = authenticate(c, setup[2])
        result = feed(c, p, "motion_comic", shanghai_date(), lane="creator")
        assert result["total"] == ("2" if browser else "1")
        assert result["items"][0]["entry"]["observation"]["view_count"] == "326000"
        assert result["items"][0]["comment_sample_count"] == (1 if mode == "complete" else None)
        from app.intelligence.feedback import entry_feedback

        detail = entry_feedback(
            c, p, UUID(str(result["items"][0]["entry"]["id"])), "motion_comic", shanghai_date()
        )
        assert detail["status"] == ("sampled" if mode == "complete" else "not_acquired")
        assert len(detail["comments"]) == (1 if mode == "complete" else 0)
        if mode == "complete":
            assert "第1集" in detail["sampling_description"]
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM sources WHERE org_id=%s AND enabled AND name LIKE '博主短剧 · %%'",
                (setup[0],),
            ).scalar_one()
            == 0
        )
        assert c.exec_driver_sql(
            "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
        ).scalar_one() == (4 if mode == "complete" else 3)
    assert len(calls) == (
        5 if mode == "complete" else 4
    )  # identity read + catalog + first-episode mapping + comments

    if browser:
        from datetime import UTC, datetime

        from app.collection.creator_browser_comments import BrowserComments, run
        from app.connectors.douyin_browser_session import sample_bundle
        from app.tasks.service import external_calls, unresolved_calls
        from tests.test_douyin_browser_session import response_pages

        ep, first, second, _ = response_pages()

        def visitor(sid, uid):
            import copy

            pages = copy.deepcopy([ep, first, second])
            pages[0]["parameters"]["series_id"] = sid
            pages[0]["body"]["aweme_list"][0]["series_info"]["series_id"] = sid
            data = sample_bundle(pages, sid, uid)
            data.update(
                series_id=sid,
                uid=uid,
                captured_at=datetime.now(UTC).isoformat(),
                method="dedicated_browser_network_json",
                status="sampled",
            )
            return data

        with engine.begin() as c:
            snap = c.exec_driver_sql(
                "SELECT id FROM intelligence_snapshots WHERE org_id=%s AND view_kind='creator_works'",
                (p.org_id,),
            ).scalar_one()
        states = run(engine, p, [snap], handler=BrowserComments(visitor))
        assert states[0]["state"] == "succeeded"
        with engine.begin() as c:
            result = feed(
                c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), lane="creator"
            )
            assert result["items"][0]["comment_sample_count"] == 15
            detail = entry_feedback(
                c,
                authenticate(c, setup[2]),
                UUID(str(result["items"][0]["entry"]["id"])),
                "motion_comic",
                shanghai_date(),
            )
            assert detail["status"] == "sampled" and len(detail["comments"]) == 15
            assert external_calls(c, UUID(states[0]["task"])) == 2
            assert unresolved_calls(c, UUID(states[0]["task"])) == 0
        # A refresh targeting only the first work must preserve the second work's sample.
        states = run(engine, p, [snap], limit=1, handler=BrowserComments(visitor))
        with engine.begin() as c:
            items = feed(
                c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), lane="creator"
            )["items"]
            assert [r["comment_sample_count"] for r in items] == [15, 15]

        # A later unknown visit must not discard an earlier acknowledged capture.
        from app.tasks.service import TaskError

        visits = []

        def interrupted(sid, uid):
            visits.append(sid)
            if len(visits) == 2:
                if mode == "browser_fetch_failure":
                    value = visitor(sid, uid)
                    value.update(status="session_not_ready", safe_error="FETCH_FAILED")
                    return value
                raise TaskError("EXTERNAL_RESULT_UNKNOWN")
            return visitor(sid, uid)

        interrupted_states = run(engine, p, [snap], handler=BrowserComments(interrupted))
        assert interrupted_states[0]["state"] == "failed"
        interrupted_task = UUID(interrupted_states[0]["task"])
        with engine.begin() as c:
            acknowledged = c.exec_driver_sql(
                "SELECT id FROM raw_assets WHERE org_id=%s AND processing_task_id=%s AND external_content_id IS NOT NULL AND body_text::jsonb->>'status'='sampled'",
                (p.org_id, interrupted_task),
            ).scalar_one()
        from app.collection.creator_browser_reparse import repair

        if mode == "browser_fetch_failure":
            with engine.connect() as c:
                failed_raw = c.exec_driver_sql(
                    "SELECT id FROM raw_assets WHERE org_id=%s AND processing_task_id=%s AND external_content_id IS NOT NULL AND body_text::jsonb->>'status'='session_not_ready'",
                    (p.org_id, interrupted_task),
                ).scalar_one()
            with pytest.raises(TaskError, match="INVALID_INPUT"):
                repair(engine, p, failed_raw)
        recovered = repair(engine, p, acknowledged)
        assert recovered["state"] == "succeeded"
        # A structurally valid raw for the unknown target has no completed marker.
        import json

        from app.collection.service import insert

        with engine.begin() as c:
            original_input = c.exec_driver_sql(
                "SELECT r.body_text FROM tasks t JOIN raw_assets r ON r.org_id=t.org_id AND r.id=t.raw_asset_id WHERE t.org_id=%s AND t.id=%s",
                (p.org_id, interrupted_task),
            ).scalar_one()
            unknown_target = json.loads(original_input)["targets"][1]
            unacknowledged = visitor(unknown_target["series_id"], "123456")
            unacknowledged["snapshot_id"] = str(snap)
            text = json.dumps(unacknowledged)
            import hashlib

            unacknowledged_raw = insert(
                c,
                "raw_assets",
                p.org_id,
                origin="processing",
                asset_kind="response",
                processing_task_id=interrupted_task,
                parent_raw_asset_id=c.exec_driver_sql(
                    "SELECT raw_asset_id FROM tasks WHERE org_id=%s AND id=%s",
                    (p.org_id, interrupted_task),
                ).scalar_one(),
                external_content_id=UUID(unknown_target["content"]),
                body_text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                captured_at=datetime.now(UTC),
            )
        with pytest.raises(TaskError, match="INVALID_INPUT"):
            repair(engine, p, unacknowledged_raw)
        with engine.begin() as c:
            values = feed(
                c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), lane="creator"
            )["items"]
            assert values[0]["comment_sample_count"] == 15
            assert values[1]["comment_sample_count"] == 15  # earlier valid sample is untouched
            assert external_calls(c, UUID(recovered["task"])) == 0
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM comment_evidence ce JOIN raw_assets r ON r.org_id=ce.org_id AND r.id=ce.raw_asset_id WHERE r.org_id=%s AND r.processing_task_id=%s AND r.parent_raw_asset_id=%s",
                    (p.org_id, UUID(recovered["task"]), acknowledged),
                ).scalar_one()
                == 15
            )
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM comment_evidence ce JOIN raw_assets r ON r.org_id=ce.org_id AND r.id=ce.raw_asset_id WHERE r.org_id=%s AND r.processing_task_id=%s AND ce.content_id=%s",
                    (p.org_id, UUID(recovered["task"]), UUID(unknown_target["content"])),
                ).scalar_one()
                == 0
            )
            assert unresolved_calls(c, interrupted_task) == (
                0 if mode == "browser_fetch_failure" else 1
            )
        # Restore both test works for the following pre-existing repair assertions.
        run(engine, p, [snap], handler=BrowserComments(visitor))

        def unavailable(sid, uid):
            value = visitor(sid, uid)
            value["status"] = "session_not_ready"
            value["sample_complete"] = False
            value["comment_responses"][1]["body"]["comments"][0]["cid"] = value[
                "comment_responses"
            ][0]["body"]["comments"][-1]["cid"]
            return value

        run(engine, p, [snap], limit=1, handler=BrowserComments(unavailable))
        with engine.begin() as c:
            items = feed(
                c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), lane="creator"
            )["items"]
            assert [r["comment_sample_count"] for r in items] == [None, 15]
            saved = c.exec_driver_sql(
                "SELECT r.id FROM raw_assets r JOIN tasks t ON t.id=r.processing_task_id AND t.org_id=r.org_id WHERE r.org_id=%s AND t.kind='creator.browser.comments' AND r.external_content_id IS NOT NULL ORDER BY r.created_at DESC LIMIT 1",
                (p.org_id,),
            ).scalar_one()
        from app.collection.creator_browser_reparse import repair

        repaired = repair(engine, p, saved)
        assert repaired["state"] == "succeeded"
        with engine.begin() as c:
            items = feed(
                c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), lane="creator"
            )["items"]
            assert [r["comment_sample_count"] for r in items] == [14, 15]
            assert external_calls(c, UUID(repaired["task"])) == 0
            c.exec_driver_sql(
                "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','test repaired input withdrawal')",
                (p.org_id, saved),
            )
        from app.security.errors import Denied

        with engine.begin() as c, pytest.raises(Denied):
            entry_feedback(
                c,
                authenticate(c, setup[2]),
                UUID(str(result["items"][0]["entry"]["id"])),
                "motion_comic",
                shanghai_date(),
            )
        # Restore this target with a new valid capture, then withdraw the newest evidence.
        run(engine, p, [snap], limit=1, handler=BrowserComments(visitor))
        with engine.begin() as c:
            raw = c.exec_driver_sql(
                "SELECT raw_asset_id FROM comment_evidence WHERE org_id=%s ORDER BY captured_at DESC,id DESC LIMIT 1",
                (p.org_id,),
            ).scalar_one()
            c.exec_driver_sql(
                "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','test comment withdrawal')",
                (p.org_id, raw),
            )
        from app.security.errors import Denied

        with engine.begin() as c, pytest.raises(Denied):
            entry_feedback(
                c,
                authenticate(c, setup[2]),
                UUID(str(result["items"][0]["entry"]["id"])),
                "motion_comic",
                shanghai_date(),
            )

    # Empty terminal pages prove completeness even though they contain no selected items.
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        footer = c.exec_driver_sql(
            "SELECT r.id FROM raw_assets r JOIN collection_jobs j ON j.id=r.collection_job_id JOIN collection_calls cc ON cc.id=r.collection_call_id WHERE r.org_id=%s AND j.capability_code='douyin.creator.series' AND cc.sequence_no=2",
            (p.org_id,),
        ).scalar_one()
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','test empty terminal page')",
            (p.org_id, footer),
        )
    with engine.begin() as c:
        assert (
            feed(c, authenticate(c, setup[2]), "motion_comic", shanghai_date(), lane="creator")[
                "total"
            ]
            == "0"
        )
