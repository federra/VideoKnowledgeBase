"""Batch feedback on an isolated database and mocked provider only."""

from uuid import UUID, uuid4

import httpx
import pytest

from app.intelligence import feedback_v2 as v2
from app.intelligence import feedback_v3 as v3
from app.intelligence.feedback import entry_feedback, read_feedback
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.tasks.service import Runner
from tests.integration.test_collection import payload, prepared, task_id
from tests.integration.test_schema import raw
from tests.integration.test_security import grant
from tests.integration.test_topics import configured, handler_for

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def fixture(engine, setup, monkeypatch, tmp_path, *, count=2):
    body = payload()
    for n in range(1, count):
        body["data"]["list"].append(
            {
                **body["data"]["list"][0],
                "videoId": "second-" + str(n),
                "opusUrl": "https://www.douyin.com/video/" + str(456 + n),
            }
        )
    collector, _, org, member, _, _, req, _, token = prepared(
        engine, setup, response=lambda _: httpx.Response(200, json=body)
    )
    from app.collection.service import submit
    from app.security.sessions import authenticate

    with engine.begin() as c:
        accepted = submit(
            c,
            authenticate(c, token),
            req.model_copy(update={"max_items": count}),
            str(uuid4()),
            next(iter(collector.handlers.values())),
        )
    assert collector.run(org, task_id(accepted)) == "succeeded"
    p = configured(engine, setup, monkeypatch)
    from app.model_config import resolve

    with engine.begin() as c:
        grant(c, org, member, member, ["research.run", "file.read"])
        cfg = resolve(c, p, "motion_comic", "topic")
        entries = (
            c.exec_driver_sql(
                "SELECT e.id,o.content_id,s.business_date FROM snapshot_entries e JOIN content_observations o ON o.org_id=e.org_id AND o.id=e.content_observation_id JOIN intelligence_snapshots s ON s.org_id=e.org_id AND s.id=e.snapshot_id WHERE e.org_id=%s ORDER BY e.id",
                (org,),
            )
            .mappings()
            .all()
        )
        originals = {}
        comments = {}
        for pos, entry in enumerate(entries):
            rid = raw(c, org, member, "synthetic original " + str(pos))
            originals[entry["id"]] = rid
            cid = uuid4()
            c.exec_driver_sql(
                "INSERT INTO comment_evidence(id,org_id,content_id,raw_asset_id,platform_comment_id,body_text,like_count,captured_at,sample_position) VALUES(%s,%s,%s,%s,%s,'期待',1,clock_timestamp(),0)",
                (cid, org, entry["content_id"], rid, "batch-" + str(pos)),
            )
            comment = dict(
                c.exec_driver_sql("SELECT * FROM comment_evidence WHERE id=%s", (cid,))
                .mappings()
                .one()
            )
            comments[entry["content_id"]] = {
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
    monkeypatch.setattr(v2, "resolve", lambda *args: cfg)
    monkeypatch.setattr(v3, "resolve", lambda *args: cfg)

    def sample(c, p, snapshot, content):
        comment = comments[content["id"]]
        rid = next(originals[e["id"]] for e in entries if e["content_id"] == content["id"])
        Authorizer(c, p).read("raw_assets", rid)
        return [comment]

    monkeypatch.setattr("app.intelligence.creator_samples.sample", sample)
    calls = []
    output = {
        "items": [
            {
                "entry_id": str(e["id"]),
                "result": {
                    "result_state": "completed",
                    "summary": "独立作品小样本",
                    "claims": [
                        {
                            "kind": "emotion",
                            "claim_key": "e",
                            "text": "期待" + str(pos),
                            "trigger": "后续",
                            "sentiment": "positive",
                            "comment_ids": [str(comments[e["content_id"]]["id"])],
                        }
                    ],
                },
            }
            for pos, e in enumerate(entries)
        ]
    }
    template = handler_for(tmp_path, output, calls)
    handler = v3.FeedbackV3(template.model, template.store)
    monkeypatch.setattr("app.storage.http.get_store", lambda: template.store)
    with engine.begin() as c:
        members = [
            {
                "entry_id": e["id"],
                "sample_key": entry_feedback(c, p, e["id"], "motion_comic", e["business_date"])[
                    "sample_key"
                ],
            }
            for e in entries
        ]
    return p, entries, members, originals, handler, calls, output


def test_one_batch_two_results_single_compatibility_and_union_revocation(
    engine, setup, monkeypatch, tmp_path
):
    p, entries, members, originals, handler, calls, _ = fixture(
        engine, setup, monkeypatch, tmp_path
    )
    day = entries[0]["business_date"]
    key = uuid4()
    with engine.begin() as c:
        task = v3.start_batch(c, p, members, "motion_comic", day, key=key)
        assert v3.start_batch(c, p, members, "motion_comic", day, key=key) == task
        assert (
            v2.start(
                c,
                p,
                members[0]["entry_id"],
                "motion_comic",
                day,
                members[0]["sample_key"],
                key=uuid4(),
            )["id"]
            == task["id"]
        )
        with pytest.raises(Denied):
            v2.analysis(c, p, UUID(task["id"]))
        assert v2.analysis(c, p, UUID(task["id"]), entry_id=members[1]["entry_id"])[
            "entry_id"
        ] == str(members[1]["entry_id"])
    runner = Runner(engine, {("audience.feedback", "3"): handler}, lease_seconds=720)
    assert runner.run(p.org_id, UUID(task["id"])) == "succeeded"
    runner.run(p.org_id, UUID(task["id"]))
    assert len(calls) == 1 and len(calls[0]["messages"]) == 2
    with engine.begin() as c:
        results = [entry_feedback(c, p, e["id"], "motion_comic", day) for e in entries]
        assert len({r["feedback_id"] for r in results}) == 2
        assert [r["claims"][0]["text"] for r in results] == ["期待0", "期待1"]
        assert all(r["analysis"]["id"] == task["id"] for r in results)
        assert v3.start_batch(c, p, members, "motion_comic", day, key=uuid4())["id"] == task["id"]
        files = c.exec_driver_sql(
            "SELECT input_manifest_file_id,output_file_id FROM ai_executions WHERE task_id=%s",
            (UUID(task["id"]),),
        ).one()
        frozen_raw = c.exec_driver_sql(
            "SELECT raw_asset_id FROM tasks WHERE id=%s", (UUID(task["id"]),)
        ).scalar_one()
        for fid in files:
            assert Authorizer(c, p).read("file_objects", fid)
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM ai_executions WHERE task_id=%s", (UUID(task["id"]),)
            ).scalar_one()
            == 1
        )
        c.exec_driver_sql(
            "INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(%s,%s,%s,1,'withdrawn','test')",
            (uuid4(), p.org_id, originals[entries[1]["id"]]),
        )
    for kind, ident in [("raw_assets", frozen_raw), *[("file_objects", fid) for fid in files]]:
        with engine.begin() as c, pytest.raises(Denied):
            Authorizer(c, p).read(kind, ident)
    with engine.begin() as c, pytest.raises(Denied):
        read_feedback(c, p, results[0]["feedback_id"])


def test_invalid_batch_no_partial_and_explicit_retry(engine, setup, monkeypatch, tmp_path):
    p, entries, members, _, handler, calls, output = fixture(engine, setup, monkeypatch, tmp_path)
    output["items"][1]["result"]["claims"][0]["comment_ids"] = output["items"][0]["result"][
        "claims"
    ][0]["comment_ids"]
    day = entries[0]["business_date"]
    with engine.begin() as c:
        task = v3.start_batch(c, p, members, "motion_comic", day, key=uuid4())
    assert (
        Runner(engine, {("audience.feedback", "3"): handler}, lease_seconds=720).run(
            p.org_id, UUID(task["id"])
        )
        == "failed"
    )
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM feedback_snapshots WHERE task_id=%s", (UUID(task["id"]),)
            ).scalar_one()
            == 0
        )
        with pytest.raises(Denied):
            v3.start_batch(c, p, members, "motion_comic", day, key=uuid4())
    retry = [{**x, "retry_of": UUID(task["id"])} for x in members]
    with engine.begin() as c:
        result = v3.start_batch(c, p, retry, "motion_comic", day, key=uuid4())
        assert result["id"] != task["id"]
    assert len(calls) == 1


def test_batch_rejects_wrong_sample_duplicate_and_mixed_active(
    engine, setup, monkeypatch, tmp_path
):
    p, entries, members, _, _, calls, _ = fixture(engine, setup, monkeypatch, tmp_path)
    day = entries[0]["business_date"]
    for invalid in [[members[0], members[0]], [{**members[0], "sample_key": "0" * 64}, members[1]]]:
        with engine.begin() as c, pytest.raises(Denied):
            v3.start_batch(c, p, invalid, "motion_comic", day, key=uuid4())
    with engine.begin() as c:
        v2.start(
            c, p, members[0]["entry_id"], "motion_comic", day, members[0]["sample_key"], key=uuid4()
        )
    with engine.begin() as c, pytest.raises(Denied):
        v3.start_batch(c, p, members, "motion_comic", day, key=uuid4())
    assert not calls


@pytest.mark.parametrize("count", [1, 3])
def test_batch_tail_and_three_members_with_independent_insufficient(
    engine, setup, monkeypatch, tmp_path, count
):
    p, entries, members, _, handler, calls, output = fixture(
        engine, setup, monkeypatch, tmp_path, count=count
    )
    last = output["items"][-1]["result"]
    last.update(result_state="insufficient_evidence", summary=None)
    last["claims"][0].update(sentiment="unclassifiable", text="无法判断", trigger="语义不明")
    day = entries[0]["business_date"]
    with engine.begin() as c:
        task = v3.start_batch(c, p, members, "motion_comic", day, key=uuid4())
    assert (
        Runner(engine, {("audience.feedback", "3"): handler}, lease_seconds=720).run(
            p.org_id, UUID(task["id"])
        )
        == "succeeded"
    )
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM feedback_snapshots WHERE task_id=%s", (UUID(task["id"]),)
            ).scalar_one()
            == count
        )
        assert (
            v2.analysis(c, p, UUID(task["id"]), entry_id=members[-1]["entry_id"])["result_state"]
            == "insufficient_evidence"
        )
        if count == 1:
            assert v2.analysis(c, p, UUID(task["id"]))["entry_id"] == str(members[0]["entry_id"])
    assert len(calls) == 1


def test_batch_changed_config_and_wrong_date_make_zero_calls(engine, setup, monkeypatch, tmp_path):
    from datetime import timedelta

    p, entries, members, _, handler, calls, _ = fixture(engine, setup, monkeypatch, tmp_path)
    day = entries[0]["business_date"]
    with engine.begin() as c, pytest.raises(Denied):
        v3.start_batch(c, p, members, "motion_comic", day - timedelta(days=1), key=uuid4())
    with engine.begin() as c:
        task = v3.start_batch(c, p, members, "motion_comic", day, key=uuid4())
    cfg = v3.resolve(None, None, None, None)
    monkeypatch.setattr(v3, "resolve", lambda *args: {**cfg, "binding_lock_version": "999"})
    assert (
        Runner(engine, {("audience.feedback", "3"): handler}, lease_seconds=720).run(
            p.org_id, UUID(task["id"])
        )
        == "failed"
    )
    assert not calls


def test_typed_guard_rejects_forged_frozen_sample(engine, setup, monkeypatch, tmp_path):
    import hashlib
    import json
    from datetime import UTC, datetime

    from sqlalchemy.exc import DBAPIError

    from app.collection.service import insert
    from app.core.repository import create_task

    p, entries, members, _, _, calls, _ = fixture(engine, setup, monkeypatch, tmp_path)
    day = entries[0]["business_date"]
    with engine.begin() as c:
        good = v3.start_batch(c, p, members, "motion_comic", day, key=uuid4())
        task = dict(
            c.exec_driver_sql("SELECT * FROM tasks WHERE id=%s", (UUID(good["id"]),))
            .mappings()
            .one()
        )
        data = json.loads(
            c.exec_driver_sql(
                "SELECT body_text FROM raw_assets WHERE id=%s", (task["raw_asset_id"],)
            ).scalar_one()
        )
        inputs = [
            dict(x)
            for x in c.exec_driver_sql(
                "SELECT * FROM task_inputs WHERE task_id=%s ORDER BY position", (task["id"],)
            ).mappings()
        ]
    data["members"][1]["sample"]["comments"][0]["id"] = data["members"][0]["sample"]["comments"][0][
        "id"
    ]
    text = json.dumps(data, ensure_ascii=False)
    with pytest.raises(DBAPIError, match="feedback v3 invalid sample linkage"), engine.begin() as c:
        raw_id = insert(
            c,
            "raw_assets",
            p.org_id,
            origin="manual",
            asset_kind="response",
            submitted_by=p.member_id,
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=datetime.now(UTC),
        )
        new_id = uuid4()
        values = {
            k: task[k]
            for k in (
                "org_id",
                "kind",
                "handler_version",
                "source_id",
                "business_code",
                "requested_by",
                "execution_authorized_by",
                "max_attempts",
                "max_external_calls",
            )
        }
        values.update(
            id=new_id, raw_asset_id=raw_id, idempotency_key=str(new_id), input_sha256="d" * 64
        )
        for x in inputs:
            for k in ("org_id", "task_id", "position", "created_at"):
                x.pop(k, None)
            if x["role"] == "freeze":
                x["raw_asset_id"] = raw_id
        create_task(c, values, inputs)
    assert not calls
