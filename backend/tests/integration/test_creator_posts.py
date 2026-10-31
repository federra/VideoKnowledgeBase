import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.connectors.redfox import Reply
from app.intelligence.creator_contracts import CreatorBatch
from app.intelligence.creators import save, view
from app.intelligence.refresh import start
from app.intelligence.refresh_worker import runtime
from app.security.sessions import authenticate
from tests.integration.test_feed_refresh import authorize
from tests.test_douyin_posts import page, post

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


@pytest.mark.parametrize("fail", [False, True])
def test_story_posts_window_numeric_global_order_and_preserve_ai(engine, setup, monkeypatch, fail):
    from app.intelligence import creator_posts
    from app.intelligence.service import feed, shanghai_date

    authorize(engine, setup)
    calls = []
    now = datetime.now(ZoneInfo("Asia/Shanghai"))

    class Connector:
        before_request = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def resolve(self, url):
            if self.before_request:
                self.before_request()
            sec = url.rsplit("/", 1)[-1]
            uid = "123456" if sec == "MS4w_test" else "223456"
            calls.append(("profile", sec))
            return {
                "status": 200,
                "body": json.dumps(
                    {
                        "status_code": 0,
                        "user": {"uid": uid, "sec_uid": sec, "nickname": "博主" + uid},
                    }
                ),
                "error": None,
            }

        def fetch(self, sec, cursor):
            calls.append(("posts", sec, cursor))
            if self.before_request:
                self.before_request()
            uid = "123456" if sec == "MS4w_test" else "223456"
            rows = [
                post(int(uid) + i, now - timedelta(hours=1), "9" if sec == "MS4w_test" else "32")
                for i in range(12)
            ]
            for r in rows:
                r["author"].update(uid=uid, sec_uid=sec, nickname="博主" + uid)
            return Reply(
                200,
                None,
                "invalid_shape" if fail else "success",
                json.dumps(page(rows)),
                datetime.now(ZoneInfo("Asia/Shanghai")),
                error="INVALID_RESPONSE" if fail else None,
            )

    monkeypatch.setattr(creator_posts, "connector_factory", Connector)
    monkeypatch.setattr("app.intelligence.creator_resolution.PROFILE_INTERVAL", 0)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        save(
            c,
            p,
            CreatorBatch(business_code="motion_comic", links="https://www.douyin.com/user/MS4w_ai"),
            str(uuid4()),
        )
        save(
            c,
            p,
            CreatorBatch(
                business_code="story_short",
                links="https://www.douyin.com/user/MS4w_test\nhttps://www.douyin.com/user/MS4w_other",
            ),
            str(uuid4()),
        )
        batch = start(c, p, "story_short", str(uuid4()), creators_only=True)
    assert runtime(engine).run(setup[0], UUID(batch["task_id"])) == "succeeded"
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        result = feed(c, p, "story_short", shanghai_date(), lane="creator")
        assert result["total"] == ("0" if fail else "24"), list(
            c.exec_driver_sql(
                "SELECT kind,state,safe_error_code FROM tasks WHERE org_id=%s ORDER BY created_at",
                (p.org_id,),
            )
        )
        if not fail:
            assert all(x["entry"]["observation"]["like_count"] == "32" for x in result["items"])
            assert len(result["items"]) == 10
            assert view(c, p, "story_short")["items"][0]["display_name"] == "博主123456"
        assert len(view(c, p, "motion_comic")["items"]) == 1
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM sources WHERE org_id=%s AND business_code='story_short' AND enabled",
                (p.org_id,),
            ).scalar_one()
            == 0
        )
        assert not c.exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM comment_evidence WHERE org_id=%s)", (p.org_id,)
        ).scalar_one()
    assert not any(call[0] not in ("profile", "posts") for call in calls)
