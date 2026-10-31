import json
import time

import pytest

from app.connectors import douyin_posts_http as dh
from app.connectors.redfox import AdapterError


def test_sdk_gate_stops_on_real_403_and_survives_new_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "ROOT", tmp_path)
    calls = []
    source = dh.SessionPosts()
    result = source._guard(lambda: calls.append(1) or {"status": 403, "body": "restricted"})
    assert result["status"] == 403
    gate = json.loads((tmp_path / "public-series/request-gate.json").read_text())
    assert gate["blocked_until"] > time.time() + 86000
    with pytest.raises(AdapterError):
        dh.SessionPosts()._guard(lambda: calls.append(2))
    assert calls == [1]


def test_profile_403_without_post_template_still_persists_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "ROOT", tmp_path)
    source = dh.SessionPosts()

    class Page:
        def route(self, *a):
            pass

        def on(self, *a):
            pass

        def goto(self, *a, **kw):
            source.profile_result = {"status": 403, "body": "restricted", "error": None}
            return type("Response", (), {"status": 200})()

        def wait_for_timeout(self, *a):
            pass

    source.context = type("Context", (), {"new_page": lambda self: Page()})()
    ticks = iter([0, 1, 31, 32])
    monkeypatch.setattr(dh.time, "monotonic", lambda: next(ticks))
    result = source._guard(lambda: source._prepare("MS4w_test", True) or source.profile_result)
    assert result["status"] == 403
    assert (
        json.loads((tmp_path / "public-series/request-gate.json").read_text())["blocked_until"]
        > time.time()
    )


def test_control_fence_is_not_mislabeled_as_external_unknown(tmp_path, monkeypatch):
    from app.tasks.service import TaskError

    monkeypatch.setattr(dh, "ROOT", tmp_path)
    source = dh.SessionPosts()

    def revoked():
        raise TaskError("ACCESS_REVOKED")

    source.before_request = revoked
    with pytest.raises(TaskError, match="ACCESS_REVOKED"):
        source.fetch("MS4w_test", 0)


def test_cooldown_prevents_starting_browser_session(tmp_path, monkeypatch):
    monkeypatch.setattr(dh, "ROOT", tmp_path)
    d = tmp_path / "public-series"
    d.mkdir()
    (d / "request-gate.json").write_text(json.dumps({"blocked_until": time.time() + 1000}))

    def forbidden_profile():
        raise AssertionError("profile must not be opened in cooldown")

    monkeypatch.setattr(dh, "exclusive_profile", forbidden_profile)
    with pytest.raises(AdapterError, match="SOURCE_UNAVAILABLE"):
        dh.SessionPosts().__enter__()


def test_paging_preserves_only_native_session_uifid_header(monkeypatch):
    source = dh.SessionPosts()
    source.sec = 'MS4w_test'
    source.allowed = None

    class Request:
        resource_type = 'fetch'
        url = 'https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id=MS4w_test&max_cursor=0&count=18'
        headers = {'uifid': 'native-session-value', 'cookie': 'never-copy', 'x-other': 'never-copy'}

    class Route:
        request = Request()
        def abort(self):
            pass
        def continue_(self):
            pass

    source._route(Route())  # The native bootstrap is inspected, not sent.
    monkeypatch.setattr(source, '_guard', lambda operation: operation())
    monkeypatch.setattr(source, '_prepare', lambda *args: None)

    class Page:
        def evaluate(self, script, payload):
            assert payload['headers'] == {'uifid': 'native-session-value'}
            assert 'setRequestHeader' in script
            return {'status': 200, 'body': '{"status_code":0,"aweme_list":[]}', 'url': dh.HOST + dh.POST}

    source.page = Page()
    result = source.fetch('MS4w_test', 123)
    assert result.error is None


def test_explicit_headed_maintenance_uses_same_connector_policy():
    source = dh.SessionPosts(headless=False)
    assert source.headless is False
