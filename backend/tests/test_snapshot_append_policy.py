"""Safety boundaries for the operational snapshot importer (no external requests)."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

spec = spec_from_file_location(
    "append_snapshot", Path(__file__).resolve().parents[2] / "scripts/append_collection_snapshot.py"
)
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_server_only_and_modified_rows_are_preserved_by_difference_policy():
    before = {"same": "a", "server-edited": "b", "server-only": "c"}
    source = {"same": "a", "server-edited": "d", "new": "e"}
    result = module.compare(before, source)
    assert result["missing"] == ["new"]
    assert result["existing_different_preserved"] == 1
    assert result["target_only_preserved"] == 1
    module.unchanged({"rows": before}, {"rows": {**before, "new": "e"}})
    with pytest.raises(RuntimeError, match="Existing target row changed"):
        module.unchanged({"rows": before}, {"rows": {**source, "server-only": "c"}})


@pytest.mark.parametrize(
    "source,target",
    [
        ("cip_video_knowledge", "cip_video_knowledge"),
        ("postgres", "cip_sync_test_fixture"),
        ("cip_stage_fixture", "postgres"),
        ("cip_stage_fixture", "other_business_database"),
    ],
)
def test_database_boundary_rejected_before_connection(source, target):
    with pytest.raises(ValueError):
        module.run(source, target, execute=True)


@pytest.mark.parametrize("table", ["raw_asset_events", "file_objects"])
def test_unsupported_evidence_dependency_stops_before_copy(monkeypatch, table):
    before = {"raw_asset_events": {}, "file_objects": {}}
    definitions = {"raw_asset_events": ["id"], "file_objects": ["id"]}
    monkeypatch.setattr(
        module, "row_map", lambda c, name, keys: {'["extra"]': "hash"} if name == table else {}
    )
    with pytest.raises(RuntimeError, match="Unsupported dependency delta: " + table):
        module.scope_gate(None, definitions, before, {}, {})
