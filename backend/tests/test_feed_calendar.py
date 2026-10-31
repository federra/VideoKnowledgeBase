"""Latest empty/denied versions must not resurrect an older populated version."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.intelligence import calendar as module
from app.security.errors import Denied


@pytest.mark.parametrize("new_count", [0, 2])
def test_calendar_newest_version_has_no_older_fallback(monkeypatch, new_count):
    today = date(2026, 10, 30)
    p = SimpleNamespace(org_id="org")
    snapshots = [
        {
            "id": ident,
            "business_date": today,
            "source_id": "source",
            "view_kind": "board",
            "entry_count": count,
            "platform_code": "douyin",
            "capability_code": "douyin.series.hot",
        }
        for ident, count in [("new", new_count), ("old", 2)]
    ]
    c = Mock()
    c.execute.return_value.mappings.return_value = snapshots
    monkeypatch.setattr(module, "shanghai_date", lambda: today)
    monkeypatch.setattr(module, "ReadAuthorizer", Mock())
    monkeypatch.setattr(module, "prepare", Mock())

    def authorize(c, p, snap, auth):
        if snap["id"] == "new":
            raise Denied("NOT_FOUND")
        return [{}]

    read = Mock(side_effect=authorize)
    monkeypatch.setattr(module, "authorized", read)
    assert module.calendar(c, p, "motion_comic", "2026-10")["dates"] == []
    assert all(call.args[2]["id"] != "old" for call in read.call_args_list)
