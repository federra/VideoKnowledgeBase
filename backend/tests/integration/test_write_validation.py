"""Transaction-local full validation reuse must never weaken deferred guards."""

from uuid import uuid4

import pytest

from tests.integration.test_schema import base, connection, execute

pytestmark = pytest.mark.database
__all__ = ["connection"]


def audit(c, org, member, n=1):
    for _ in range(n):
        execute(
            c,
            "INSERT INTO audit_events(id,org_id,actor_member_id,action_code,target_kind,request_id) VALUES(%s,%s,%s,'test.validation','task',%s)",
            (uuid4(), org, member, str(uuid4())),
        )


def state(c, org):
    return dict(
        execute(
            c,
            "SELECT generation,integrity_generation,relationships_generation,integrity_runs,relationships_runs FROM cip_integrity_runtime.validation_state WHERE org_id=%s",
            (org,),
        )
        .mappings()
        .one()
    )


def invalid_artifact(c, org, member, work):
    execute(
        c,
        "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES(%s,%s,%s,%s,'script',%s)",
        (uuid4(), org, work, str(uuid4()), member),
    )


def test_full_validation_once_per_transaction_generation(connection):
    c = connection
    org, member, _ = base(c)
    audit(c, org, member, 20)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    s = state(c, org)
    assert s["integrity_runs"] == s["relationships_runs"] == 1
    assert s["generation"] == s["integrity_generation"] == s["relationships_generation"]
    execute(c, "SET CONSTRAINTS ALL DEFERRED")
    audit(c, org, member, 5)
    execute(
        c, "UPDATE works SET name='changed',lock_version=lock_version+1 WHERE org_id=%s", (org,)
    )
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    s = state(c, org)
    assert s["integrity_runs"] == s["relationships_runs"] == 2


@pytest.mark.parametrize("constraint", ["ALL", "zz_integrity", "zz_relationships"])
def test_write_after_explicit_validation_is_not_skipped(connection, constraint):
    c = connection
    org, member, work = base(c)
    execute(c, f"SET CONSTRAINTS {constraint} IMMEDIATE")
    execute(c, "SET CONSTRAINTS ALL DEFERRED")
    invalid_artifact(c, org, member, work)
    with pytest.raises(Exception, match="current pointer required"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_savepoint_failed_generation_rolls_back(connection):
    c = connection
    org, member, work = base(c)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    execute(c, "SET CONSTRAINTS ALL DEFERRED")
    save = c.begin_nested()
    invalid_artifact(c, org, member, work)
    with pytest.raises(Exception, match="current pointer required"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    save.rollback()
    execute(c, "UPDATE works SET name='changed',lock_version=lock_version+1 WHERE id=%s", (work,))
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    s = state(c, org)
    assert s["integrity_runs"] == s["relationships_runs"] == 2


def test_savepoint_validation_mark_rolls_back(connection):
    c = connection
    org, _member, _ = base(c)
    save = c.begin_nested()
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    save.rollback()
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    s = state(c, org)
    assert s["integrity_runs"] == s["relationships_runs"] == 1


def test_two_organizations_validate_independently(connection):
    c = connection
    a, ma, _ = base(c)
    b, mb, _ = base(c)
    audit(c, a, ma, 3)
    audit(c, b, mb, 2)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    assert state(c, a)["integrity_runs"] == state(c, b)["integrity_runs"] == 1


def test_state_is_not_client_controlled(connection):
    from app.core.database_roles import grant_application

    c = connection
    org, member, _ = base(c)
    role = "cip_test_validation_" + uuid4().hex
    execute(c, "CREATE ROLE " + role + " NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
    grant_application(c.connection.driver_connection.cursor(), role)
    execute(c, "SET ROLE " + role)
    for statement in [
        "SELECT * FROM cip_integrity_runtime.validation_state",
        "UPDATE cip_integrity_runtime.validation_state SET integrity_generation=generation",
        "SELECT * FROM cip_integrity_runtime.function_backup",
    ]:
        save = c.begin_nested()
        with pytest.raises(Exception, match="permission denied"):
            execute(c, statement)
        save.rollback()
    execute(c, "SET cip.validation_done='true'")
    execute(c, "CREATE TEMP TABLE validation_state(org_id uuid,integrity_generation bigint)")
    audit(c, org, member, 3)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    execute(c, "RESET ROLE")
    assert state(c, org)["integrity_runs"] == 1
    # Role creation is transactional and rolled back by fixture; no cluster role remains.


@pytest.mark.parametrize("mode", ["disabled", "conditional"])
def test_uncovered_table_cannot_reuse_another_write_mark(connection, mode):
    c = connection
    org, member, work = base(c)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    execute(c, "SET CONSTRAINTS ALL DEFERRED")
    # Fault injection for a future table/trigger regression; transactional DDL is rolled back.
    if mode == "disabled":
        execute(c, "ALTER TABLE artifacts DISABLE TRIGGER a0_tenant_lock")
    else:
        execute(c, "DROP TRIGGER a0_tenant_lock ON artifacts")
        execute(
            c,
            "CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON artifacts FOR EACH ROW WHEN(false) EXECUTE FUNCTION cip_write_lock()",
        )
    invalid_artifact(c, org, member, work)
    with pytest.raises(Exception, match="current pointer required"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


@pytest.fixture
def committed_engine():
    import os

    from app.core.database import build_engine

    url = os.environ.get("CIP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated PostgreSQL required")
    engine = build_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_new_transaction_never_reuses_previous_generation(committed_engine):
    e = committed_engine
    with e.begin() as c:
        org, member, work = base(c)
    with e.begin() as c:
        audit(c, org, member)
        execute(c, "UPDATE works SET name='first',lock_version=lock_version+1 WHERE id=%s", (work,))
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
        first = state(c, org)
    with pytest.raises(Exception, match="current pointer required"), e.begin() as c:
        invalid_artifact(c, org, member, work)
    with e.begin() as c:
        audit(c, org, member)
        execute(
            c, "UPDATE works SET name='second',lock_version=lock_version+1 WHERE id=%s", (work,)
        )
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
        second = state(c, org)
    assert first["generation"] == second["generation"] == 2
    assert first["integrity_runs"] == second["integrity_runs"] == 1


def test_concurrent_same_org_writer_cannot_reuse_first_mark(committed_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    e = committed_engine
    with e.begin() as c:
        org, member, work = base(c)
    ready, release, attempt = Event(), Event(), Event()
    pids = {}

    def a():
        with e.begin() as c:
            pids["a"] = execute(c, "SELECT pg_backend_pid()").scalar_one()
            execute(
                c,
                "UPDATE works SET name='first writer',lock_version=lock_version+1 WHERE id=%s",
                (work,),
            )
            execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
            ready.set()
            assert release.wait(5)

    def b():
        assert ready.wait(5)
        with pytest.raises(Exception, match="current pointer required"), e.begin() as c:
            pids["b"] = execute(c, "SELECT pg_backend_pid()").scalar_one()
            attempt.set()
            invalid_artifact(c, org, member, work)
        return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(a)
        fb = pool.submit(b)
        try:
            assert attempt.wait(5)
            import time

            deadline = time.monotonic() + 3
            with e.connect() as observer:
                while True:
                    blockers = execute(
                        observer, "SELECT pg_blocking_pids(%s)", (pids["b"],)
                    ).scalar_one()
                    if pids["a"] in blockers:
                        break
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                assert (
                    execute(
                        observer,
                        "SELECT wait_event FROM pg_stat_activity WHERE pid=%s",
                        (pids["b"],),
                    ).scalar_one()
                    == "advisory"
                )
            assert not fb.done()
        finally:
            release.set()
        fa.result(timeout=10)
        assert fb.result(timeout=10) == "rejected"


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_stale_snapshot_must_serialize_fail_not_skip(committed_engine, isolation):
    e = committed_engine
    with e.begin() as c:
        org, member, _ = base(c)
    with e.connect().execution_options(isolation_level=isolation) as stale:
        execute(stale, "SELECT count(*) FROM audit_events WHERE org_id=%s", (org,))
        with e.begin() as c:
            audit(c, org, member)
        with pytest.raises(Exception, match="serialize|serialization"):
            audit(stale, org, member)
        stale.rollback()


def test_audit_only_transaction_needs_no_unrelated_full_guard(committed_engine):
    e = committed_engine
    with e.begin() as c:
        org, member, _ = base(c)
    with e.begin() as c:
        audit(c, org, member, 10)
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
        s = state(c, org)
    assert s["integrity_runs"] == s["relationships_runs"] == 0


def test_monotonic_lease_renewal_needs_no_full_content_guard(committed_engine):
    from tests.integration.test_schema import task

    e = committed_engine
    with e.begin() as c:
        org, member, work = base(c)
        tid = task(c, org, member, work)
        v = execute(c, "SELECT lock_version FROM tasks WHERE id=%s", (tid,)).scalar_one()
        attempt, token, version = execute(
            c, "SELECT * FROM cip_claim_task(%s,%s,%s,3600)", (org, tid, v)
        ).one()
    try:
        with e.begin() as c:
            execute(
                c,
                "SELECT cip_task_control(%s,%s,%s,'renew',%s,%s,3600,NULL)",
                (org, tid, version, attempt, token),
            )
            execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
            s = state(c, org)
        assert s["integrity_runs"] == s["relationships_runs"] == 0
    finally:
        with e.begin() as c:
            execute(
                c,
                "SELECT cip_finish_task(%s,%s,%s,%s,%s,'failed',NULL,'INTERNAL_ERROR')",
                (org, tid, attempt, token, version),
            )


def test_privileged_trigger_functions_are_not_publicly_executable(connection):
    c = connection
    assert (
        execute(
            c,
            "SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid IN('cip_write_lock()'::regprocedure,'cip_validate()'::regprocedure,'cip_relationships()'::regprocedure) AND a.grantee=0 AND a.privilege_type='EXECUTE'",
        ).scalar_one()
        == 0
    )


def test_column_limited_write_lock_is_not_complete_coverage(connection):
    c = connection
    _org, _, work = base(c)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    execute(c, "SET CONSTRAINTS ALL DEFERRED")
    execute(c, "DROP TRIGGER a0_tenant_lock ON works")
    execute(
        c,
        "CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OF name OR DELETE ON works FOR EACH ROW EXECUTE FUNCTION cip_write_lock()",
    )
    execute(
        c, "UPDATE works SET report_generation=1,lock_version=lock_version+1 WHERE id=%s", (work,)
    )
    with pytest.raises(Exception, match="report generation"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_named_guards_keep_independent_validation_marks(connection):
    c = connection
    org, _, _ = base(c)
    execute(c, "SET CONSTRAINTS zz_integrity IMMEDIATE")
    s = state(c, org)
    assert s["integrity_runs"] == 1 and s["relationships_runs"] == 0
    execute(c, "SET CONSTRAINTS zz_relationships IMMEDIATE")
    assert state(c, org)["relationships_runs"] == 1


def test_relationships_revalidate_after_an_earlier_named_check(connection):
    from app.core.repository import claim_task

    c = connection
    org, member, work = base(c)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    execute(c, "SET CONSTRAINTS ALL DEFERRED")
    artifact, version, ident, child = [uuid4() for _ in range(4)]
    execute(
        c,
        "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES(%s,%s,%s,%s,'script',%s)",
        (artifact, org, work, str(artifact), member),
    )
    execute(
        c,
        "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,material_kind,body_text,content_sha256,created_by) VALUES(%s,%s,%s,%s,1,'script','text',%s,%s)",
        (version, org, artifact, work, "8" * 64, member),
    )
    execute(
        c,
        "INSERT INTO tasks(id,org_id,kind,handler_version,work_id,requested_by,execution_authorized_by,idempotency_key,input_sha256) VALUES(%s,%s,'parse','1',%s,%s,%s,%s,%s)",
        (ident, org, work, member, member, str(ident), "0" * 64),
    )
    execute(
        c,
        "INSERT INTO task_inputs(org_id,task_id,position,role,artifact_version_id) VALUES(%s,%s,0,'material',%s)",
        (org, ident, version),
    )
    execute(c, "SELECT cip_seal('tasks',%s,%s,'inputs')", (org, ident))
    claim_task(c, org, ident, 2)
    execute(
        c,
        "INSERT INTO raw_assets(id,org_id,origin,asset_kind,processing_task_id,parent_artifact_version_id,body_text,sha256,captured_at) VALUES(%s,%s,'processing','transcript',%s,%s,'derived',%s,clock_timestamp())",
        (child, org, ident, version, "9" * 64),
    )
    execute(
        c,
        "INSERT INTO artifact_version_sources VALUES(%s,%s,%s,'transcript')",
        (org, version, child),
    )
    execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
    execute(
        c,
        "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (version, artifact),
    )
    with pytest.raises(Exception, match="cycle"):
        execute(c, "SET CONSTRAINTS zz_relationships IMMEDIATE")


def test_deferred_organization_fk_keeps_child_before_parent(connection):
    c = connection
    org, member = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO members(id,org_id,login_name,display_name) VALUES(%s,%s,%s,'late parent')",
        (member, org, str(member)),
    )
    execute(c, "INSERT INTO organizations(id,name) VALUES(%s,'late parent')", (org,))
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    assert state(c, org)["integrity_runs"] == 1


def test_downgrade_refuses_changed_effective_acl(connection):
    from migrations.integrity import read_snapshot

    c = connection
    # Rollback fixture means no permissions are changed in the shared test database.
    execute(c, "GRANT EXECUTE ON FUNCTION cip_validate() TO PUBLIC")
    with (
        pytest.raises(Exception, match="privileges changed"),
        c.connection.driver_connection.cursor() as cursor,
    ):
        cursor.execute(read_snapshot("0037_down.sql"), prepare=False)
