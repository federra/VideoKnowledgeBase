"""Real isolated-PostgreSQL shared entry, permissions and CSRF regression."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytest_plugins = ('tests.integration.test_security',)
pytestmark = pytest.mark.database


@pytest.mark.parametrize("origin,secure", [("http://workspace.test:8080", False),
                                           ("https://workspace.test:8443", True)])
def test_shared_entry_reuses_owner_and_preserves_csrf_permissions(engine, monkeypatch, origin, secure):
    from app.core.config import settings
    from app.main import app
    from app.security.http import get_engine
    from app.security.local import enter

    with engine.begin() as c:
        _, existing = enter(c)
    monkeypatch.setattr(settings, 'passwordless_access', True)
    monkeypatch.setattr(settings, 'local_single_user', False)
    monkeypatch.setattr(settings, 'allowed_origins', [origin])
    monkeypatch.setattr(settings, 'secure_cookies', secure)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url=origin,
                            client=('203.0.113.5', 5000))
        entry = client.get('/api/v1/session')
        assert entry.status_code == 200, entry.text
        data = entry.json()['data']
        assert data['org_id'] == str(existing['org_id'])
        assert data['member_id'] == str(existing['member_id'])
        assert 'HttpOnly' in entry.headers['set-cookie']
        assert 'SameSite=strict' in entry.headers['set-cookie']
        assert ('; Secure' in entry.headers['set-cookie']) is secure
        body = {'name': 'shared paused source', 'address': '漫剧', 'business_code': 'motion_comic'}
        headers = {'Origin': origin, 'Idempotency-Key': str(uuid4())}
        assert client.post('/api/v1/sources', json=body, headers=headers).status_code == 403
        headers['X-CSRF-Token'] = data['csrf_token']
        result = client.post('/api/v1/sources', json=body, headers=headers)
        assert result.status_code == 201, result.text
        assert result.json()['data']['enabled'] is False
        assert client.post('/api/v1/sources', json=body,
                           headers={**headers, 'Origin': 'http://evil.test'}).status_code == 403
        assert client.post('/api/v1/session', json={}).status_code == 403
        assert client.delete('/api/v1/session', headers=headers).status_code == 403
        assert client.get('/api/v1/session',
                          headers={'Host': 'evil.test',
                                   'X-Forwarded-Host': 'workspace.test:8080'}).status_code == 403
        assert client.get('/api/v1/session',
                          headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        with engine.begin() as c:
            c.exec_driver_sql('UPDATE members SET disabled_at=clock_timestamp(), lock_version=lock_version+1 WHERE id=%s',
                              (data['member_id'],))
        assert client.get('/api/v1/sources').status_code == 401
        assert client.get('/api/v1/session').status_code == 401
        with engine.connect() as c:
            assert c.exec_driver_sql('SELECT count(*) FROM collection_calls WHERE org_id=%s',
                                     (data['org_id'],)).scalar_one() == 0
    finally:
        with engine.begin() as c:
            c.exec_driver_sql('UPDATE members SET disabled_at=NULL, lock_version=lock_version+1 WHERE id=%s',
                              (existing['member_id'],))
        app.dependency_overrides.clear()
