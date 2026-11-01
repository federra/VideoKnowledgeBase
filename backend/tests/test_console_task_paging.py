"""List output traversal must be bounded by the authorized page, not task history."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from app.collection import console


def test_task_page_traverses_outputs_only_after_authorized_filter_and_paging(monkeypatch):
    org, member = UUID(int=1), UUID(int=2)
    p = SimpleNamespace(org_id=org, member_id=member)
    now = datetime.now(UTC)
    rows = [
        {
            "id": UUID(int=i + 10),
            "org_id": org,
            "created_at": now - timedelta(seconds=i),
            "business_code": "motion_comic",
            "kind": "collect.redfox",
            "requested_by": member,
            "source_id": None,
            "work_id": None,
            "raw_asset_id": None,
        }
        for i in range(8)
    ]

    class Result:
        def mappings(self):
            return self

        def all(self):
            return rows

        def scalars(self):
            return iter(r["id"] for r in rows)

    class Connection:
        def exec_driver_sql(self, *_):
            return Result()

    class Auth:
        def __init__(self, *_):
            self.rows = {("tasks", r["id"]): r for r in rows}

        def _refresh(self):
            pass

        def row(self, kind, ident):
            return self.rows[(kind, ident)]

        def personal(self, kind, ident):
            pass

        def scopes(self, kind, row):
            return {("task", str(row["id"]))}

        def allowed(self, action, scopes):
            return ("task", str(rows[0]["id"])) not in scopes

    viewed = []

    def view(c, p, ident, **_):
        viewed.append(ident)
        return {
            "id": str(ident),
            "created_at": next(r["created_at"].isoformat() for r in rows if r["id"] == ident),
        }

    def paginate(c, p, data, **kwargs):
        assert kwargs == {
            "kind": "tasks",
            "business": "motion_comic",
            "limit": 2,
            "cursor": "after",
            "q": "collect",
        }
        assert data["total"] == "7"  # inaccessible rows excluded before total/cursor
        return {"items": data["items"][2:4], "next_cursor": "following", "total": "7"}

    monkeypatch.setattr(console, "refresh", lambda *_: None)
    monkeypatch.setattr(console, "ReadAuthorizer", Auth, raising=False)
    monkeypatch.setattr(console, "TaskReadAuthorizer", Auth, raising=False)
    monkeypatch.setattr(console, "task_view", view)
    monkeypatch.setattr(console, "page", paginate, raising=False)
    result = console.list_tasks(
        Connection(), p, "motion_comic", limit=2, cursor="after", q="collect"
    )
    assert viewed == [rows[3]["id"], rows[4]["id"]]
    assert result["total"] == "7" and result["next_cursor"] == "following"
