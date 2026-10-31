import json

import httpx
import pytest

from app.connectors.douyin_public_http import PublicDouyin, resolve
from app.tasks.service import TaskError


def test_invalid_identity_keeps_original_response_and_completed_http(tmp_path):
    body = {'status_code': 0, 'series_infos': [], 'cursor': 0, 'has_more': 0}
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    result = resolve('https://www.douyin.com/user/MS4w_test', PublicDouyin(client, tmp_path))
    assert result['status'] == 200 and result['error'] == 'INVALID_RESPONSE'
    assert json.loads(result['body']) == body


def test_wait_rechecks_fence_before_network_and_does_not_retry(tmp_path, monkeypatch):
    calls, checks = [], []
    def forbidden(_):
        calls.append('network')
        raise AssertionError('network must not run after cancellation')
    connector = PublicDouyin(httpx.Client(transport=httpx.MockTransport(forbidden)), tmp_path)
    def cancelled():
        checks.append('checked')
        raise TaskError('ACCESS_REVOKED')
    connector.before_request = cancelled
    with pytest.raises(TaskError, match='ACCESS_REVOKED'):
        connector.fetch('catalog', 'MS4w_test')
    assert checks == ['checked'] and calls == []


def test_source_403_creates_persistent_cooldown_and_never_paid_fallback(tmp_path):
    calls = []
    def blocked(request):
        calls.append(request.url.host)
        assert not request.headers.get('cookie')
        assert not request.headers.get('authorization')
        return httpx.Response(403, text='blocked')
    client = httpx.Client(transport=httpx.MockTransport(blocked))
    first = PublicDouyin(client, tmp_path).fetch('catalog', 'MS4w_test')
    assert first.error == 'SOURCE_UNAVAILABLE'
    with pytest.raises(ValueError, match='SOURCE_UNAVAILABLE'):
        PublicDouyin(client, tmp_path).fetch('catalog', 'MS4w_test')
    assert calls == ['www.douyin.com']
