from uuid import uuid4

import pytest

from app.intelligence.creator_contracts import CreatorBatch, CreatorRemove
from app.intelligence.creators import save, view
from app.security.errors import Denied
from app.security.sessions import authenticate
from tests.integration.test_feed_refresh import authorize

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_batch_valid_lines_dedup_removal_business_isolation_and_zero_calls(engine, setup):
    authorize(engine, setup)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        body = CreatorBatch(
            business_code="motion_comic",
            links="https://www.douyin.com/user/MS4wLjAB123?share=1\nhttps://douyin.com/user/MS4wLjAB123\nhttps://evil.com/user/a",
        )
        key = str(uuid4())
        result = save(c, p, body, key)
        assert [x["state"] for x in result["results"]] == ["added", "duplicate", "invalid"]
        assert save(c, p, body, key) == result
        assert len(view(c, p, "motion_comic")["items"]) == 1
        assert not view(c, p, "story_short")["items"]
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM tasks WHERE org_id=%s", (p.org_id,)
            ).scalar_one()
            == 0
        )
        save(
            c,
            p,
            CreatorRemove(business_code="motion_comic", creator_id=result["items"][0]["id"]),
            str(uuid4()),
            remove=True,
        )
        assert not view(c, p, "motion_comic")["items"]
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM raw_assets WHERE org_id=%s AND origin='manual'", (p.org_id,)
            ).scalar_one()
            == 2
        )


def test_configuration_requires_permission_before_replay(engine, setup):
    with engine.begin() as c, pytest.raises(Denied):
        view(c, authenticate(c, setup[2]), "motion_comic")


def test_legacy_paid_works_provider_is_never_used_for_creator_refresh(engine, setup, monkeypatch):
    from uuid import UUID

    import httpx

    from app.connectors.douyin_public_http import PublicDouyin
    from app.connectors.redfox import RedFox
    from app.intelligence import creator_series
    from app.intelligence.refresh import latest, start
    from app.intelligence.refresh_worker import runtime

    authorize(engine, setup)
    paid_calls = []
    monkeypatch.setattr(RedFox, 'fetch', lambda *_a, **_k: paid_calls.append('paid'))
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text='blocked')))
    monkeypatch.setattr(creator_series, 'PublicDouyin', lambda: PublicDouyin(client, __import__('pathlib').Path('/tmp') / str(uuid4())))
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        save(c, p, CreatorBatch(business_code='motion_comic', links='https://www.douyin.com/user/MS4wLjAB123'), str(uuid4()))
        job = start(c, p, 'motion_comic', str(uuid4()), creators_only=True)
    assert runtime(engine).run(setup[0], UUID(job['task_id'])) == 'succeeded'
    assert not paid_calls
    with engine.begin() as c:
        assert latest(c, authenticate(c, setup[2]), 'motion_comic')['channels'][0]['state'] == 'failed'


def test_removed_config_and_unverifiable_profile_never_call_paid_provider(
    engine, setup, monkeypatch
):
    from uuid import UUID

    from pydantic import SecretStr

    from app.core.config import settings
    from app.intelligence import creator_resolution, creator_series
    from app.intelligence.refresh import latest, start
    from app.intelligence.refresh_worker import runtime

    authorize(engine, setup)
    monkeypatch.setattr(settings, "redfox_api_key", SecretStr("test-only"))
    calls = []

    from datetime import UTC, datetime

    from app.connectors.redfox import Reply
    class Blocked:
        def fetch(self, *args):
            calls.append(args)
            return Reply(403, None, 'http_error', 'blocked', datetime.now(UTC), error='SOURCE_UNAVAILABLE')
    monkeypatch.setattr(creator_series, 'PublicDouyin', Blocked)

    monkeypatch.setattr(creator_resolution, "PROFILE_INTERVAL", 0)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        result = save(
            c,
            p,
            CreatorBatch(
                business_code="motion_comic", links="https://www.douyin.com/user/MS4wLjAB123"
            ),
            str(uuid4()),
        )
        job = start(c, p, "motion_comic", str(uuid4()))
        save(
            c,
            p,
            CreatorRemove(business_code="motion_comic", creator_id=result["items"][0]["id"]),
            str(uuid4()),
            remove=True,
        )
    assert runtime(engine).run(setup[0], UUID(job["task_id"])) == "succeeded"
    assert not calls
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        save(
            c,
            p,
            CreatorBatch(
                business_code="motion_comic", links="https://www.douyin.com/user/MS4wLjAB123"
            ),
            str(uuid4()),
        )
        job = start(c, p, "motion_comic", str(uuid4()))
    assert runtime(engine).run(setup[0], UUID(job["task_id"])) == "succeeded"
    assert len(calls) == 1
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        assert latest(c, p, "motion_comic")["channels"][-1]["state"] == "failed"
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM collection_calls WHERE org_id=%s", (setup[0],)
            ).scalar_one()
            == 0
        )
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM audit_events WHERE org_id=%s AND action_code='creator.profile.requested'",
                (setup[0],),
            ).scalar_one()
            == 1
        )


def test_profile_first_request_of_new_batch_respects_persisted_cooldown(engine, setup, monkeypatch):
    from uuid import UUID

    from pydantic import SecretStr

    from app.core.config import settings
    from app.intelligence import creator_series
    from app.intelligence.refresh import start
    from app.intelligence.refresh_worker import runtime
    from app.security.storage import audit

    authorize(engine, setup)
    monkeypatch.setattr(settings, "redfox_api_key", SecretStr("test-only"))
    calls = []
    class MustNotFetch:
        def fetch(self, *args):
            calls.append(args)
            raise AssertionError('persisted gate must stop all HTTP')
    monkeypatch.setattr(creator_series, 'PublicDouyin', MustNotFetch)
    with engine.begin() as c:
        p = authenticate(c, setup[2])
        # A committed reservation from another task remains visible to a fresh Runner.
        audit(c, p.org_id, p.member_id, "creator.profile.requested", "task", uuid4())
        save(
            c,
            p,
            CreatorBatch(
                business_code="motion_comic", links="https://www.douyin.com/user/MS4wLjAB123"
            ),
            str(uuid4()),
        )
        job = start(c, p, "motion_comic", str(uuid4()))
    assert runtime(engine).run(setup[0], UUID(job["task_id"])) == "succeeded"
    assert calls == []
    with engine.begin() as c:
        assert (
            c.exec_driver_sql(
                "SELECT safe_error_code FROM tasks WHERE org_id=%s AND kind='creator.resolve'",
                (setup[0],),
            ).scalar_one()
            == "RATE_LIMITED"
        )


def test_creator_cards_reuse_verified_name_and_hide_withdrawn_identity_without_requests(engine, setup):
    import hashlib
    from sqlalchemy import func
    from app.collection.service import identity, insert
    from app.intelligence.creators import current
    authorize(engine,setup)
    with engine.begin() as c:
        p=authenticate(c,setup[2])
        saved=save(c,p,CreatorBatch(business_code='motion_comic',links='https://www.douyin.com/user/MS4wLjAB123'),str(uuid4()))
        assert saved['items'][0]['platform_uid'] is None
        assert saved['items'][0]['display_name'] is None
        import json
        body=json.dumps({'status_code':0,'series_infos':[{'author':{'uid':'123456','sec_uid':'MS4wLjAB123','nickname':'容量夏然短剧'}}],'has_more':0,'cursor':0})
        raw=insert(c,'raw_assets',p.org_id,origin='manual',asset_kind='response',submitted_by=p.member_id,body_text=body,sha256=hashlib.sha256(body.encode()).hexdigest(),captured_at=func.clock_timestamp())
        account=identity(c,'external_accounts',p.org_id,'platform_uid','123456')
        insert(c,'external_account_aliases',p.org_id,account_id=account,alias_kind='sec_uid',alias_value='MS4wLjAB123',raw_asset_id=raw,observed_at=func.clock_timestamp())
        assert view(c,p,'motion_comic')['items'][0]['platform_uid']=='123456'
        assert view(c,p,'motion_comic')['items'][0]['display_name']=='容量夏然短剧'
        assert set(current(c,p.org_id,'motion_comic')[1][0])=={'id','url'}
        c.exec_driver_sql("INSERT INTO raw_asset_events(id,org_id,raw_asset_id,event_no,event_kind,reason) VALUES(gen_random_uuid(),%s,%s,1,'access_revoked','test card identity withdrawal')",(p.org_id,raw))
        assert view(c,p,'motion_comic')['items'][0]['platform_uid'] is None
        assert view(c,p,'motion_comic')['items'][0]['display_name'] is None
        assert c.exec_driver_sql('SELECT count(*) FROM tasks WHERE org_id=%s',(p.org_id,)).scalar_one()==0
