"""Same-day continuation with fake external channels, never live provider calls."""

from uuid import UUID, uuid4

import pytest

from tests.integration.test_feed_refresh import authorize

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_resume_skips_published_channels_and_preserves_original_terminal(
    engine, setup, monkeypatch
):
    from app.intelligence.refresh import latest, publish_channel, start
    from app.intelligence.refresh_resume import ResumeChannels, runner, start_resume
    from app.security.sessions import authenticate
    from app.tasks.service import TaskError

    authorize(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        bid = UUID(start(c, p, "motion_comic", str(uuid4()))["task_id"])
    from app.intelligence.refresh import KIND, VERSION
    from app.intelligence.refresh_worker import Refresh
    from app.tasks.service import Runner

    def failed(self, r, t, check):
        with engine.begin() as c:
            original = c.exec_driver_sql("SELECT * FROM tasks WHERE id=%s", (bid,)).mappings().one()
            publish_channel(c, original, "hongguo")
            publish_channel(c, original, "tikhub")
        raise TaskError("ACCESS_REVOKED")

    monkeypatch.setattr(Refresh, "execute_ticket", failed)
    assert Runner(engine, {(KIND, VERSION): Refresh()}).run(p.org_id, bid) == "failed"
    with engine.begin() as c:
        tid = start_resume(c, p, bid)
    calls = []

    def remaining(self, name):
        calls.append(name)
        self.publish_channel(name)
        return "succeeded"

    monkeypatch.setattr(ResumeChannels, "run", remaining)
    assert runner(engine).run(p.org_id, tid) == "succeeded"
    assert calls == ["fanqie", "qidian"]
    with engine.begin() as c:
        assert latest(c, p, "motion_comic")["task_id"] == str(tid)
        assert (
            c.exec_driver_sql("SELECT state FROM tasks WHERE id=%s", (bid,)).scalar_one()
            == "failed"
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
        with pytest.raises(TaskError):
            start_resume(c, p, tid)

        from app.core.repository import create_task

        create_task(
            c,
            {
                "org_id": p.org_id,
                "kind": "creator.resolve",
                "business_code": "motion_comic",
                "raw_asset_id": c.exec_driver_sql(
                    "SELECT raw_asset_id FROM tasks WHERE id=%s", (bid,)
                ).scalar_one(),
                "handler_version": "1",
                "requested_by": p.member_id,
                "execution_authorized_by": p.member_id,
                "idempotency_key": "creator-resolve/" + str(bid) + "/entry/1",
                "input_sha256": "a" * 64,
            },
        )
        with pytest.raises(TaskError, match="INVALID_INPUT"):
            start_resume(c, p, bid)
