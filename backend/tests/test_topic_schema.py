"""Topics inventory remains separate from B1 and excludes synthetic evidence."""

import sqlalchemy as sa

from app.core.models import MUTABLE, TABLE_GROUPS, metadata

NAMES = (
    "topic_cards",
    "topic_revisions",
    "topic_sparks",
    "topic_spark_revisions",
    "topic_saved_generations",
    "topic_handoffs",
)


def test_topics_are_independent_versioned_objects():
    assert all(name in metadata.tables for name in NAMES)
    assert not set(NAMES).intersection([name for group in TABLE_GROUPS for name in group])
    for name in NAMES:
        t = metadata.tables[name]
        assert {"id", "org_id", "created_at"} <= set(t.c.keys())
        targets = {fk.target_fullname for fk in t.foreign_keys}
        assert "organizations.id" in targets
        assert "members.org_id" in targets
        assert all(fk.deferrable and fk.initially == "DEFERRED" for fk in t.foreign_key_constraints)
    assert set(MUTABLE["topic_cards"]) == {
        "status",
        "current_revision_id",
        "selected_revision_id",
        "updated_at",
        "lock_version",
    }
    assert set(MUTABLE["topic_sparks"]) == {"current_revision_id", "updated_at", "lock_version"}
    assert all(name not in MUTABLE for name in NAMES if name not in ("topic_cards", "topic_sparks"))


def test_topic_pointer_and_save_uniqueness():
    for name, parent, column in (
        ("topic_cards", "topic_revisions", "topic_id"),
        ("topic_sparks", "topic_spark_revisions", "spark_id"),
    ):
        pointers = [
            fk
            for fk in metadata.tables[name].foreign_key_constraints
            if any(e.target_fullname.startswith(parent + ".") for e in fk.elements)
        ]
        assert pointers
        for fk in pointers:
            assert [e.target_fullname for e in fk.elements] == [
                parent + ".org_id",
                parent + "." + column,
                parent + ".id",
            ]
    constraints = metadata.tables["topic_saved_generations"].constraints
    assert any(
        isinstance(c, sa.UniqueConstraint) and list(c.columns.keys()) == ["org_id", "task_id"]
        for c in constraints
    )
