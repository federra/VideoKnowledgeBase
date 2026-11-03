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


def test_private_dependency_index_keeps_multi_owner_edges_and_expires():
    from app.security.read_authorizer import ReadAuthorizer

    class Rows:
        def __init__(self, value):
            self.value = value

        def mappings(self):
            return self.value

        def __iter__(self):
            return iter(self.value)

    calls = []
    transaction = [object()]
    tasks = [
        {"id": "ta", "requested_by": "alice", "raw_asset_id": "manifest", "file_id": "task-file"},
        {"id": "tb", "requested_by": "bob", "raw_asset_id": "manifest", "file_id": None},
    ]

    def query(sql, params):
        calls.append(sql)
        assert params[0] == "org"
        if "FROM tasks WHERE" in sql:
            return Rows(tasks)
        if "FROM task_outputs" in sql:
            return Rows([("ta", "result")])
        if "FROM raw_assets" in sql:
            return Rows([("result", "tb", "raw-file"), ("manifest", None, "manifest-file")])
        if "FROM ai_executions" in sql:
            return Rows([("tb", "input-file", "output-file")])
        raise AssertionError(sql)

    c = SimpleNamespace(exec_driver_sql=query, get_transaction=lambda: transaction[0])
    p = SimpleNamespace(org_id="org", member_id="alice")
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
    ):
        az = ReadAuthorizer(c, p)
        for kind, ident, expected in [
            ("tasks", "ta", {"alice"}),
            ("raw_assets", "manifest", {"alice", "bob"}),
            ("raw_assets", "result", {"alice", "bob"}),
            ("file_objects", "raw-file", {"alice", "bob"}),
            ("file_objects", "manifest-file", {"alice", "bob"}),
            ("file_objects", "task-file", {"alice"}),
            ("file_objects", "input-file", {"bob"}),
            ("file_objects", "output-file", {"bob"}),
            ("raw_assets", "foreign", set()),
        ]:
            assert set(az.personal_dependencies(kind, ident)) == expected
        assert len(calls) == 4
        az.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        assert set(az.personal_dependencies("raw_assets", "result")) == {"alice", "bob"}
        assert len(calls) == 8
        transaction[0] = object()
        assert set(az.personal_dependencies("file_objects", "output-file")) == {"bob"}
        assert len(calls) == 12


def test_recursive_checks_copy_only_at_external_boundary():
    from copy import deepcopy

    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    az = None

    def check(self, kind, ident, action, path=()):
        if ident == "root":
            child = self.check(kind, "child", action, (*path, (kind, ident)))
            return {"id": ident, "child": child}
        return {"id": ident, "tags": [{"value": "safe"}]}

    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch("app.security.authorization.Authorizer.check", check),
        patch("app.security.read_authorizer.deepcopy", wraps=deepcopy) as clone,
    ):
        az = ReadAuthorizer(None, p)
        returned = az.read("sources", "root")
        returned["child"]["tags"][0]["value"] = "changed"
        assert az.read("sources", "root")["child"]["tags"][0]["value"] == "safe"
        # External callers with a supplied provenance path still receive isolated data.
        returned = az.check("sources", "child", "content.read", (("sources", "root"),))
        returned["tags"].clear()
        assert az.read("sources", "root")["child"]["tags"] == [{"value": "safe"}]
        assert clone.call_count == 4


def test_recursive_failure_resets_copy_boundary():
    import pytest

    from app.security.errors import Denied
    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    failed = [False]

    def check(self, kind, ident, action, path=()):
        if not failed[0]:
            failed[0] = True
            self.check(kind, "child", action, ((kind, ident),))
            raise Denied("NOT_FOUND")
        return {"id": ident, "values": ["original"]}

    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch("app.security.authorization.Authorizer.check", check),
    ):
        az = ReadAuthorizer(None, p)
        with pytest.raises(Denied, match="NOT_FOUND"):
            az.read("sources", "root")
        returned = az.read("sources", "root")
        returned["values"].clear()
        assert az.read("sources", "root")["values"] == ["original"]


def test_scalar_rows_keep_return_isolation_without_deepcopy():
    from copy import deepcopy
    from decimal import Decimal
    from uuid import uuid4

    from app.security.read_authorizer import ReadAuthorizer

    p = SimpleNamespace(org_id="org", member_id="member")
    saved = {
        "id": uuid4(),
        "created_at": datetime.now(UTC),
        "title": "original",
        "n": 1,
        "amount": Decimal("1.25"),
        "empty": None,
    }
    with (
        patch("app.security.read_authorizer.refresh", return_value={}),
        patch("app.security.read_authorizer.active_grants", return_value=[]),
        patch("app.security.authorization.Authorizer.check", return_value=saved),
        patch("app.security.read_authorizer.deepcopy", wraps=deepcopy) as clone,
    ):
        az = ReadAuthorizer(None, p)
        returned = az.read("sources", "scalar")
        returned["title"] = "changed"
        assert az.read("sources", "scalar") == saved
        assert returned is not saved
        assert clone.call_count == 0
