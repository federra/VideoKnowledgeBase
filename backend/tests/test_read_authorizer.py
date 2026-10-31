from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch


def test_read_batch_reuses_checks_but_new_batch_revalidates():
    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch("app.security.authorization.Authorizer.check", return_value={"id": "x"}) as check,
    ):
        auth = ReadAuthorizer(None, p)
        assert auth.read("sources", "x") == auth.read("sources", "x")
        assert check.call_count == 1
        ReadAuthorizer(None, p).read("sources", "x")
        assert check.call_count == 2


def test_expired_grant_invalidates_cached_checks():
    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch("app.security.authorization.Authorizer.check", return_value={"id": "x"}) as check,
    ):
        auth = ReadAuthorizer(None, p)
        auth.read("sources", "x")
        auth.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        auth.read("sources", "x")
        assert check.call_count == 2


def test_new_transaction_discards_memo():
    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    from unittest.mock import Mock

    c = Mock()
    c.get_transaction.return_value = object()
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch("app.security.authorization.Authorizer.check", return_value={"id": "x"}) as check,
    ):
        auth = ReadAuthorizer(c, p)
        auth.read("sources", "x")
        c.get_transaction.return_value = object()
        auth.read("sources", "x")
        assert check.call_count == 2


def test_grant_expiring_during_database_read_is_not_cached_as_permanent():
    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    expired = {
        "action_code": "content.read",
        "scope_kind": "org",
        "expires_at": datetime.now(UTC) - timedelta(seconds=1),
    }
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[expired]),
    ):
        auth = ReadAuthorizer(None, p)
        assert not auth.allowed("content.read", {("org", "org")})


def test_source_state_and_parent_memos_expire_with_authorization():
    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch(
            "app.security.authorization.Authorizer.raw_asset_state", side_effect=[None, "withdrawn"]
        ) as state,
        patch(
            "app.security.authorization.Authorizer.provenance_parents",
            side_effect=[["r:parent"], ["r:changed"]],
        ) as parents,
    ):
        auth = ReadAuthorizer(None, p)
        assert auth.raw_asset_state("raw") is None
        returned = auth.provenance_parents("r:raw")
        returned.clear()
        assert auth.raw_asset_state("raw") is None
        assert auth.provenance_parents("r:raw") == ["r:parent"]
        assert state.call_count == parents.call_count == 1
        auth.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        assert auth.raw_asset_state("raw") == "withdrawn"
        assert auth.provenance_parents("r:raw") == ["r:changed"]
        assert state.call_count == parents.call_count == 2
