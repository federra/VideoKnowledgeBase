"""Real PostgreSQL constraints for additive topics (disposable database only)."""

from uuid import uuid4

import pytest
from sqlalchemy import inspect

from tests.integration.test_schema import base, connection, execute, task

pytestmark = pytest.mark.database
__all__ = ["connection"]


def topic(c, org, member, *, version=1):
    identity, revision = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO topic_cards(id,org_id,business_code,current_revision_id,created_by) "
        "VALUES (%s,%s,'motion_comic',%s,%s)",
        (identity, org, revision, member),
    )
    execute(
        c,
        "INSERT INTO topic_revisions(id,org_id,topic_id,version_no,fields,origin,"
        "source_refs,content_sha256,created_by) "
        "VALUES (%s,%s,%s,%s,'{}','manual','{}',%s,%s)",
        (revision, org, identity, version, "a" * 64, member),
    )
    return identity, revision


def test_topics_catalog_matches_metadata(connection):
    from app.core.models import metadata

    inspector = inspect(connection)
    for name in (
        "topic_cards",
        "topic_revisions",
        "topic_sparks",
        "topic_spark_revisions",
        "topic_saved_generations",
        "topic_handoffs",
    ):
        actual = {c["name"]: c for c in inspector.get_columns(name)}
        model = metadata.tables[name]
        assert set(actual) == set(model.c.keys())
        assert all(actual[col.name]["nullable"] == col.nullable for col in model.c)
        assert len(inspector.get_foreign_keys(name)) == len(model.foreign_key_constraints)


def test_topic_revisions_and_exact_handoff(connection):
    c = connection
    org, member, _ = base(c)
    identity, revision = topic(c, org, member)
    execute(
        c,
        "UPDATE topic_cards SET status='production',selected_revision_id=%s,"
        "lock_version=lock_version+1 WHERE id=%s",
        (revision, identity),
    )
    execute(
        c,
        "INSERT INTO topic_handoffs(id,org_id,topic_id,topic_revision_id,method,created_by) "
        "VALUES (%s,%s,%s,%s,'copy',%s)",
        (uuid4(), org, identity, revision, member),
    )
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Exception, match="immutable"):
        execute(
            c, 'UPDATE topic_revisions SET fields=\'{"title":"changed"}\' WHERE id=%s', (revision,)
        )


@pytest.mark.parametrize("pointer", ["current_revision_id", "selected_revision_id"])
def test_topics_reject_other_parent_pointer(connection, pointer):
    c = connection
    org, member, _ = base(c)
    identity, _ = topic(c, org, member)
    _, other_revision = topic(c, org, member)
    with pytest.raises(Exception, match="foreign key"):
        execute(
            c,
            f"UPDATE topic_cards SET {pointer}=%s,lock_version=lock_version+1 WHERE id=%s",
            (other_revision, identity),
        )
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_topics_reject_cross_organization_member(connection):
    c = connection
    org, _, _ = base(c)
    _, member, _ = base(c)
    with pytest.raises(Exception, match="foreign key"):
        topic(c, org, member)
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_topics_require_single_version_advance(connection):
    c = connection
    org, member, _ = base(c)
    with pytest.raises(Exception, match="revision must advance once"):
        topic(c, org, member, version=2)


def test_topics_require_lock_advance(connection):
    c = connection
    org, member, _ = base(c)
    identity, _ = topic(c, org, member)
    with pytest.raises(Exception, match="lock_version must advance once"):
        execute(c, "UPDATE topic_cards SET status='production' WHERE id=%s", (identity,))


def test_brainstorm_task_cannot_be_saved_twice(connection):
    c = connection
    org, member, work = base(c)
    generation = task(c, org, member, work)
    identity, _ = topic(c, org, member)
    execute(
        c,
        "INSERT INTO topic_saved_generations(id,org_id,task_id,topic_id,created_by) "
        "VALUES (%s,%s,%s,%s,%s)",
        (uuid4(), org, generation, identity, member),
    )
    with pytest.raises(Exception, match="unique"):
        execute(
            c,
            "INSERT INTO topic_saved_generations(id,org_id,task_id,topic_id,created_by) "
            "VALUES (%s,%s,%s,%s,%s)",
            (uuid4(), org, generation, identity, member),
        )


def test_spark_revision_requires_owner(connection):
    c = connection
    org, member, _ = base(c)
    identity, revision = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO topic_sparks(id,org_id,owner_member_id,current_revision_id) "
        "VALUES (%s,%s,%s,%s)",
        (identity, org, member, revision),
    )
    execute(
        c,
        "INSERT INTO topic_spark_revisions(id,org_id,spark_id,version_no,text,title,created_by) "
        "VALUES (%s,%s,%s,1,'spark','title',%s)",
        (revision, org, identity, member),
    )
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Exception, match="immutable"):
        execute(c, "DELETE FROM topic_spark_revisions WHERE id=%s", (revision,))


def test_spark_rejects_other_member_edit(connection):
    c = connection
    org, member, _ = base(c)
    other_member, identity, revision = uuid4(), uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,'other')",
        (other_member, org, str(other_member)),
    )
    execute(
        c,
        "INSERT INTO topic_sparks(id,org_id,owner_member_id,current_revision_id) "
        "VALUES (%s,%s,%s,%s)",
        (identity, org, member, revision),
    )
    with pytest.raises(Exception, match="spark revision requires owner"):
        execute(
            c,
            "INSERT INTO topic_spark_revisions(id,org_id,spark_id,version_no,text,title,"
            "created_by) VALUES (%s,%s,%s,1,'spark','title',%s)",
            (revision, org, identity, other_member),
        )


def test_handoff_rejects_other_topic_version(connection):
    c = connection
    org, member, _ = base(c)
    identity, _ = topic(c, org, member)
    _, other_revision = topic(c, org, member)
    with pytest.raises(Exception, match="foreign key"):
        execute(
            c,
            "INSERT INTO topic_handoffs(id,org_id,topic_id,topic_revision_id,method,"
            "created_by) VALUES (%s,%s,%s,%s,'export',%s)",
            (uuid4(), org, identity, other_revision, member),
        )
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
