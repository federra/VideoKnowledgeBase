"""Focused HTTP regression around the explicitly enabled local workspace."""

import pytest
from fastapi.testclient import TestClient

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_local_auto_entry_still_requires_same_origin_csrf_and_no_paid_side_effect(
    engine, monkeypatch
):
    from app.core.config import settings
    from app.main import app
    from app.security.http import get_engine

    monkeypatch.setattr(settings, "local_single_user", True)
    app.dependency_overrides[get_engine] = lambda: engine
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234))
        data = client.get("/api/v1/session").json()["data"]
        body = {"name": "本地暂停来源", "address": "漫剧", "business_code": "motion_comic"}
        from uuid import uuid4

        headers = {"Origin": "http://127.0.0.1:5173", "Idempotency-Key": str(uuid4())}
        assert client.post("/api/v1/sources", json=body, headers=headers).status_code != 201
        headers["X-CSRF-Token"] = data["csrf_token"]
        result = client.post("/api/v1/sources", json=body, headers=headers)
        assert result.status_code == 201, result.text
        assert result.json()["data"]["enabled"] is False
        assert (
            client.post(
                "/api/v1/sources", json=body, headers={**headers, "Origin": "https://evil.invalid"}
            ).status_code
            == 403
        )
        with engine.connect() as c:
            assert (
                c.exec_driver_sql(
                    "SELECT count(*) FROM collection_calls WHERE org_id=%s", (data["org_id"],)
                ).scalar_one()
                == 0
            )
    finally:
        app.dependency_overrides.clear()
