"""Shared workspace transport boundaries; no database or external requests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.core.config import Settings, settings
from app.security.errors import Denied
from app.security.http import preflight


def request(url='http://workspace.test:8080', method='GET', path='/api/v1/session', **headers):
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return Request({
        'type': 'http', 'method': method, 'scheme': parts.scheme,
        'path': path, 'query_string': b'',
        'server': (parts.hostname, parts.port or 80),
        'client': ('203.0.113.5', 4000),
        'headers': [(k.lower().replace('_', '-').encode(), v.encode())
                    for k, v in {'host': parts.netloc, **headers}.items()],
    })


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'passwordless_access', True)
    monkeypatch.setattr(settings, 'allowed_origins', ['http://workspace.test:8080'])
    monkeypatch.setattr(settings, 'secure_cookies', False)


def test_shared_entry_requires_explicit_configuration(monkeypatch):
    monkeypatch.setenv('PASSWORDLESS_ACCESS', 'true')
    config = Settings(_env_file=None)
    assert getattr(config, 'passwordless_access', False) is True
    monkeypatch.delenv('PASSWORDLESS_ACCESS')
    assert getattr(Settings(_env_file=None), 'passwordless_access', False) is False


def test_shared_remote_get_session_is_allowed_without_proxy_header_spoof(shared):
    engine = object()
    assert preflight(request(), engine) is engine


@pytest.mark.parametrize('url,headers', [
    ('http://evil.test:8080', {}),
    ('http://workspace.test:8081', {}),
    ('https://workspace.test:8080', {}),
    ('http://workspace.test:8080', {'origin': 'http://evil.test'}),
    ('http://workspace.test:8080', {'sec_fetch_site': 'cross-site'}),
    ('http://evil.test', {'x_forwarded_host': 'workspace.test:8080',
                          'x_forwarded_proto': 'http'}),
    ('http://workspace.test:8080', {'host': 'workspace.test:8080,evil.test'}),
])
def test_shared_entry_rejects_untrusted_authority_or_browser_context(shared, url, headers):
    with pytest.raises(Denied):
        preflight(request(url, **headers), object())


@pytest.mark.parametrize('method', ['POST', 'DELETE'])
def test_shared_session_only_accepts_get(shared, method):
    with pytest.raises(Denied) as exc:
        preflight(request(method=method), object())
    assert exc.value.code == 'ACCESS_DENIED'


def test_shared_secure_cookie_mode_requires_https(shared, monkeypatch):
    monkeypatch.setattr(settings, 'secure_cookies', True)
    monkeypatch.setattr(settings, 'allowed_origins', ['https://workspace.test'])
    with pytest.raises(Denied):
        preflight(request('http://workspace.test'), object())
    engine = object()
    assert preflight(request('https://workspace.test'), engine) is engine


def test_shared_cookie_keeps_configured_secure_flag(shared, monkeypatch):
    from contextlib import nullcontext

    from app.security import http, local

    monkeypatch.setattr(local, 'enter', lambda c, raw: ('session-token', {'acknowledged': True}))
    for secure in (False, True):
        monkeypatch.setattr(settings, 'secure_cookies', secure)
        req = request()
        req.state.request_id = uuid4()
        response = http.dispatch(request=req, engine=SimpleNamespace(begin=lambda: nullcontext(None)))
        cookie = response.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
        assert ('; Secure' in cookie) is secure


def test_shared_mode_is_distinct_from_loopback_mode(shared, monkeypatch):
    monkeypatch.setattr(settings, 'local_single_user', True)
    engine = object()
    assert preflight(request(), engine) is engine
    monkeypatch.setattr(settings, 'passwordless_access', False)
    with pytest.raises(Denied):
        preflight(request(), engine)


@pytest.mark.parametrize('name,value', [('host', 'workspace.test:8080'),
                                        ('origin', 'http://workspace.test:8080')])
def test_shared_entry_rejects_duplicate_authority_headers(shared, name, value):
    req = request(origin='http://workspace.test:8080')
    req.scope['headers'].append((name.encode(), value.encode()))
    with pytest.raises(Denied):
        preflight(req, object())


def test_shared_refresh_uses_explicit_runtime_without_starting_a_collector(shared, monkeypatch):
    from app.intelligence import refresh_http

    # Execute the local thread synchronously with an inert runner; no source/network I/O.
    completed = []
    monkeypatch.setattr(refresh_http, 'runtime', lambda engine: SimpleNamespace(
        run=lambda org, task: completed.append((engine, org, task))))

    class InlineThread:
        def __init__(self, *, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(refresh_http, 'Thread', InlineThread)
    engine, org, task = object(), uuid4(), uuid4()
    refresh_http.enqueue(engine, org, task)
    assert completed == [(engine, org, task)]
    monkeypatch.setattr(settings, 'passwordless_access', False)
    with pytest.raises(Denied):
        refresh_http.enqueue(engine, org, task)
    assert completed == [(engine, org, task)]


def test_shared_https_rejects_malformed_host_without_server_error(shared, monkeypatch):
    monkeypatch.setattr(settings, 'secure_cookies', True)
    monkeypatch.setattr(settings, 'allowed_origins', ['https://workspace.test'])
    with pytest.raises(Denied):
        preflight(request('https://workspace.test', host='['), object())
