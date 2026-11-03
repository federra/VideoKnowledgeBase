"""Repeated topic sources share one read scope, never cache failed evidence."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.security.errors import Denied
from app.security.read_authorizer import ReadAuthorizer
from app.topics import service


def test_snapshot_source_success_is_reused_and_failure_is_not():
    from uuid import uuid4

    p = SimpleNamespace(org_id=uuid4(), member_id=uuid4())
    sid, raw = uuid4(), uuid4()
    snap = {"id": sid}
    refs = {"intelligence": [{"snapshot_id": str(sid), "raw_asset_id": str(raw)}] * 3}
    c = SimpleNamespace(execute=lambda *a: SimpleNamespace(first=lambda: True))
    c.get_transaction = lambda: None
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch.object(service, "row", return_value=snap),
        patch("app.intelligence.service.authorized") as verify,
    ):
        az = ReadAuthorizer(c, p)
        az.read = lambda *a: None
        service.check_sources(c, p, refs, az=az)
        service.check_sources(c, p, refs, az=az)
        assert verify.call_count == 1
        assert verify.call_args.kwargs["auth"] is az
        az.valid_until = datetime.min.replace(tzinfo=UTC)
        service.check_sources(c, p, refs, az=az)
        assert verify.call_count == 2
        verify.side_effect = Denied("SOURCE_UNAVAILABLE")
        az.projections.clear()
        for _ in range(2):
            with pytest.raises(Denied, match="SOURCE_UNAVAILABLE"):
                service.check_sources(c, p, refs, az=az)
        assert verify.call_count == 4
