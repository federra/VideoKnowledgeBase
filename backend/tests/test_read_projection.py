from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.security.read_authorizer import ReadAuthorizer


def test_read_projection_lives_only_inside_current_authorized_transaction():
    c = SimpleNamespace(get_transaction=lambda: transaction[0])
    transaction = [object()]
    calls = []
    def load():
        calls.append(True)
        return {'parsed': len(calls)}
    with patch('app.security.read_authorizer.refresh', return_value={}), patch('app.security.read_authorizer.active_grants', return_value=[]):
        auth = ReadAuthorizer(c, SimpleNamespace(org_id='o', member_id='m'))
        assert auth.memo(('page','x'), load) == auth.memo(('page','x'), load) == {'parsed':1}
        auth.valid_until = datetime.now(UTC)-timedelta(seconds=1)
        assert auth.memo(('page','x'), load) == {'parsed':2}
        transaction[0] = object()
        assert auth.memo(('page','x'), load) == {'parsed':3}
        other = ReadAuthorizer(c, auth.p)
        assert other.memo(('page','x'), load) == {'parsed':4}


def test_failed_projection_is_not_cached():
    with patch('app.security.read_authorizer.refresh', return_value={}), patch('app.security.read_authorizer.active_grants', return_value=[]):
        auth = ReadAuthorizer(None, SimpleNamespace(org_id='o',member_id='m'))
        with pytest.raises(ValueError):
            auth.memo('broken', lambda:(_ for _ in ()).throw(ValueError()))
        assert auth.memo('broken', lambda:'recovered') == 'recovered'
