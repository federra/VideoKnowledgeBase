"""Local CLI identity follows immutable installation, never mutable login name."""

import pytest

pytest_plugins = ("tests.integration.test_security",)

pytestmark = pytest.mark.database


def test_local_owner_email_setup_preserves_cli_identity_and_denies_disabled(engine, monkeypatch):
    from app.accounts.contracts import SetupRequest
    from app.accounts.service import setup
    from app.core.config import settings
    from app.security.errors import Denied
    from app.security.local import enter

    # Roll back synthetic installation as well as users; no cross-test singleton state.
    with engine.connect() as c:
        tx = c.begin()
        try:
            monkeypatch.setattr(settings, "user_accounts_enabled", False)
            _, initial = enter(c)
            org, owner = initial["org_id"], initial["member_id"]
            monkeypatch.setattr(settings, "user_accounts_enabled", True)
            setup(
                c,
                SetupRequest(
                    login_name="owner@example.test",
                    display_name="Owner",
                    password="controlled compatibility password",
                ),
            )
            before = c.exec_driver_sql("SELECT count(*) FROM organizations").scalar_one()
            _, current = enter(c)
            assert (current["org_id"], current["member_id"]) == (org, owner)
            assert c.exec_driver_sql("SELECT count(*) FROM organizations").scalar_one() == before
            from app.security.local import owner_identity

            assert tuple(owner_identity(c)) == (org, owner)
            c.exec_driver_sql(
                "UPDATE members SET disabled_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND id=%s",
                (org, owner),
            )
            for call in (enter, owner_identity):
                with pytest.raises(Denied, match="AUTH_REQUIRED"):
                    call(c)
            assert c.exec_driver_sql("SELECT count(*) FROM organizations").scalar_one() == before
        finally:
            tx.rollback()


def test_accounts_enabled_uninstalled_cli_fails_closed_and_legacy_is_unchanged(engine, monkeypatch):
    from app.core.config import settings
    from app.security.errors import Denied
    from app.security.local import enter

    with engine.connect() as c:
        tx = c.begin()
        try:
            monkeypatch.setattr(settings, "user_accounts_enabled", False)
            raw, initial = enter(c)
            repeated, same = enter(c, raw)
            assert repeated == raw and same["member_id"] == initial["member_id"]
            before = c.exec_driver_sql("SELECT count(*) FROM organizations").scalar_one()
            monkeypatch.setattr(settings, "user_accounts_enabled", True)
            with pytest.raises(Denied, match="AUTH_REQUIRED"):
                enter(c)
            assert c.exec_driver_sql("SELECT count(*) FROM organizations").scalar_one() == before
        finally:
            tx.rollback()
