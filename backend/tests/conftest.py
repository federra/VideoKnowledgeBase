import pytest


@pytest.fixture(autouse=True)
def authenticated_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "local_single_user", False)
