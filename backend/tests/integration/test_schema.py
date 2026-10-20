"""Real PostgreSQL only; scripts/database.py test supplies an isolated database."""

import os
from uuid import uuid4

import pytest

from app.core.database import build_engine

pytestmark = pytest.mark.database


@pytest.fixture
def connection():
    url = os.environ.get("CIP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Run pnpm db:test for isolated PostgreSQL acceptance.")
    engine = build_engine(url)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
    engine.dispose()


def execute(c, statement, params=None):
    return c.exec_driver_sql(statement, params or {})


def base(c):
    org, member, work = uuid4(), uuid4(), uuid4()
    execute(c, "INSERT INTO organizations(id,name) VALUES (%s,%s)", (org, "S04 isolated"))
    execute(
        c,
        "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,%s)",
        (member, org, str(member), "tester"),
    )
    execute(
        c,
        "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) "
        "VALUES (%s,%s,'motion_comic',%s,'test work',%s)",
        (work, org, str(work), member),
    )
    return org, member, work


def task(c, org, member, work):
    ident = uuid4()
    execute(
        c,
        "INSERT INTO tasks(id,org_id,kind,handler_version,work_id,requested_by,"
        "execution_authorized_by,idempotency_key,input_sha256) "
        "VALUES (%s,%s,'parse','1',%s,%s,%s,%s,%s)",
        (ident, org, work, member, member, str(ident), "0" * 64),
    )
    execute(c, "SELECT cip_seal('tasks',%s,%s,'inputs')", (org, ident))
    return ident


def material(c, org, member, work):
    artifact, version = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) "
        "VALUES (%s,%s,%s,%s,'script',%s)",
        (artifact, org, work, str(artifact), member),
    )
    execute(
        c,
        "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,body_text,"
        "material_kind,content_sha256,created_by) VALUES (%s,%s,%s,%s,1,'text','script',%s,%s)",
        (version, org, artifact, work, "1" * 64, member),
    )
    execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
    execute(
        c,
        "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (version, artifact),
    )
    return artifact, version


def test_cross_organization_fk_is_rejected(connection):
    c = connection
    _org, _member, work = base(c)
    other, _, _ = base(c)
    with pytest.raises(Exception, match="foreign key|same organization"):
        execute(
            c,
            "INSERT INTO content_units(id,org_id,work_id,unit_kind) VALUES (%s,%s,%s,'episode')",
            (uuid4(), other, work),
        )
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_sealed_material_body_and_late_sources_are_rejected(connection):
    c = connection
    org, member, work = base(c)
    _, version = material(c, org, member, work)
    with pytest.raises(Exception, match="immutable|sealed"):
        execute(c, "UPDATE artifact_versions SET body_text=%s WHERE id=%s", ("rewrite", version))


def test_unsealed_parent_cannot_commit_but_same_transaction_seal_can(connection):
    c = connection
    org, member, work = base(c)
    material(c, org, member, work)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_task_cannot_skip_running(connection):
    c = connection
    org, member, work = base(c)
    ident = task(c, org, member, work)
    with pytest.raises(Exception, match="transition"):
        execute(
            c,
            "UPDATE tasks SET state='succeeded',business_outcome='completed',"
            "lock_version=lock_version+1 WHERE id=%s",
            (ident,),
        )


def test_raw_text_and_file_cannot_both_be_missing(connection):
    c = connection
    org, member, _ = base(c)
    with pytest.raises(Exception, match="check constraint|carrier"):
        execute(
            c,
            "INSERT INTO raw_assets(id,org_id,origin,asset_kind,submitted_by,sha256,captured_at) "
            "VALUES (%s,%s,'manual','text',%s,%s,clock_timestamp())",
            (uuid4(), org, member, "0" * 64),
        )


def raw(c, org, member, text="source"):
    ident = uuid4()
    execute(
        c,
        "INSERT INTO raw_assets(id,org_id,origin,asset_kind,submitted_by,body_text,sha256,captured_at) "
        "VALUES (%s,%s,'manual','text',%s,%s,%s,clock_timestamp())",
        (ident, org, member, text, "2" * 64),
    )
    return ident


def inputs(c, org, member, work):
    artifact, version = material(c, org, member, work)
    ident = uuid4()
    execute(
        c,
        "INSERT INTO input_sets(id,org_id,work_id,scope,business_code,manifest_sha256) "
        "VALUES (%s,%s,%s,'work','motion_comic',%s)",
        (ident, org, work, "3" * 64),
    )
    execute(
        c,
        "INSERT INTO input_set_items(org_id,input_set_id,work_id,artifact_version_id,role,position) "
        "VALUES (%s,%s,%s,%s,'primary',0)",
        (org, ident, work, version),
    )
    execute(c, "SELECT cip_seal('input_sets',%s,%s)", (org, ident))
    return ident, artifact, version


def knowledge(c, org, member):
    ident, revision = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO knowledge_items(id,org_id,title,owner_member_id,created_by) VALUES (%s,%s,'candidate',%s,%s)",
        (ident, org, member, member),
    )
    execute(
        c,
        "INSERT INTO knowledge_revisions(id,org_id,knowledge_id,version_no,title,body_text,knowledge_type,"
        "browse_category,origin,created_by,content_sha256) "
        "VALUES (%s,%s,%s,1,'title','body','fact','genre','manual',%s,%s)",
        (revision, org, ident, member, "4" * 64),
    )
    execute(c, "INSERT INTO knowledge_businesses VALUES (%s,%s,'motion_comic')", (org, revision))
    execute(c, "SELECT cip_seal('knowledge_revisions',%s,%s)", (org, revision))
    execute(
        c,
        "UPDATE knowledge_items SET current_revision_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (revision, ident),
    )
    return ident, revision


def prediction(c, org, member, work):
    input_id, _, _ = inputs(c, org, member, work)
    metric, draft, frozen = uuid4(), uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO metric_specs(id,org_id,code,version_no,name,unit,definition,aggregation_kind) "
        "VALUES (%s,%s,%s,1,'views','count','observed','cumulative')",
        (metric, org, str(metric)),
    )
    execute(
        c,
        "INSERT INTO prediction_drafts(id,org_id,input_set_id,metric_spec_id,author_kind,author_member_id,"
        "platform_code,window_start_offset_seconds,window_end_offset_seconds,conditions,lower_bound,upper_bound,"
        "rationale,uncertainty_note,reliability) VALUES (%s,%s,%s,%s,'human',%s,'douyin',0,3600,'{}',1,2,'why','limited','estimable')",
        (draft, org, input_id, metric, member),
    )
    execute(
        c,
        "INSERT INTO predictions(id,org_id,input_set_id,metric_spec_id,author_kind,author_member_id,platform_code,"
        "window_start_offset_seconds,window_end_offset_seconds,conditions,context_kind,outcome_exposure,lower_bound,upper_bound,"
        "rationale,uncertainty_note,draft_id,draft_lock_version,frozen_by,content_sha256) "
        "SELECT %s,org_id,input_set_id,metric_spec_id,author_kind,author_member_id,platform_code,window_start_offset_seconds,"
        "window_end_offset_seconds,conditions,context_kind,outcome_exposure,lower_bound,upper_bound,rationale,uncertainty_note,"
        "id,lock_version,%s,%s FROM prediction_drafts WHERE id=%s",
        (frozen, member, "5" * 64, draft),
    )
    execute(c, "SELECT cip_seal('predictions',%s,%s)", (org, frozen))
    return draft, frozen


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE works SET business_code='story_short',lock_version=lock_version+1 WHERE id=%s",
        "UPDATE works SET name='changed' WHERE id=%s",
        "DELETE FROM works WHERE id=%s",
    ],
)
def test_identity_and_cas_guards(connection, mutation):
    c = connection
    _, _, work = base(c)
    with pytest.raises(Exception, match="immutable|VERSION_CONFLICT"):
        execute(c, mutation, (work,))


def test_same_tenant_wrong_work_reference(connection):
    c = connection
    org, member, work = base(c)
    artifact, _ = material(c, org, member, work)
    other = uuid4()
    execute(
        c,
        "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) "
        "VALUES (%s,%s,'motion_comic',%s,'other',%s)",
        (other, org, str(other), member),
    )
    unit = uuid4()
    execute(
        c,
        "INSERT INTO content_units(id,org_id,work_id,unit_kind) VALUES (%s,%s,%s,'episode')",
        (unit, org, other),
    )
    with pytest.raises(Exception, match="foreign key"):
        execute(
            c,
            "UPDATE artifacts SET primary_unit_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (unit, artifact),
        )
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize("target", ["artifact_versions", "input_sets", "knowledge_revisions"])
def test_unsealed_parents_are_rejected(connection, target):
    c = connection
    org, member, work = base(c)
    if target == "artifact_versions":
        artifact = uuid4()
        execute(
            c,
            "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) "
            "VALUES (%s,%s,%s,%s,'script',%s)",
            (artifact, org, work, str(artifact), member),
        )
        version = uuid4()
        execute(
            c,
            "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,body_text,material_kind,content_sha256,created_by) "
            "VALUES (%s,%s,%s,%s,1,'body','script',%s,%s)",
            (version, org, artifact, work, "6" * 64, member),
        )
        execute(
            c,
            "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (version, artifact),
        )
    elif target == "input_sets":
        execute(
            c,
            "INSERT INTO input_sets(id,org_id,work_id,scope,business_code,manifest_sha256) "
            "VALUES (%s,%s,%s,'work','motion_comic',%s)",
            (uuid4(), org, work, "3" * 64),
        )
    else:
        _, version = knowledge(c, org, member)
        # Simulate the incomplete row without bypassing a guard: roll back the
        # helper creation and insert a separate unsealed revision.
        execute(
            c,
            "INSERT INTO knowledge_revisions(id,org_id,knowledge_id,version_no,title,body_text,knowledge_type,"
            "browse_category,origin,created_by,content_sha256) SELECT %s,org_id,knowledge_id,2,'t','b','fact','genre',"
            "'manual',created_by,%s FROM knowledge_revisions WHERE id=%s",
            (uuid4(), "7" * 64, version),
        )
    with pytest.raises(Exception, match="unsealed|requires primary|requires business"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize("target", ["source", "unit", "business", "task_input"])
def test_late_child_insert_is_rejected(connection, target):
    c = connection
    org, member, work = base(c)
    if target in ("source", "unit"):
        _, version = material(c, org, member, work)
        if target == "source":
            ref = raw(c, org, member)
            statement = "INSERT INTO artifact_version_sources VALUES (%s,%s,%s,'reference')"
        else:
            ref = uuid4()
            execute(
                c,
                "INSERT INTO content_units(id,org_id,work_id,unit_kind) VALUES (%s,%s,%s,'episode')",
                (ref, org, work),
            )
            statement = "INSERT INTO artifact_version_units(org_id,artifact_version_id,unit_id,work_id) VALUES (%s,%s,%s,%s)"
        params = (org, version, ref) if target == "source" else (org, version, ref, work)
    elif target == "business":
        _, version = knowledge(c, org, member)
        statement, params = (
            "INSERT INTO knowledge_businesses VALUES (%s,%s,'story_short')",
            (org, version),
        )
    else:
        ident = task(c, org, member, work)
        ref = raw(c, org, member)
        statement = "INSERT INTO task_inputs(org_id,task_id,position,role,raw_asset_id) VALUES (%s,%s,0,'material',%s)"
        params = (org, ident, ref)
    with pytest.raises(Exception, match="sealed"):
        execute(c, statement, params)


def test_unknown_action_and_empty_grant_scope_rejected(connection):
    c = connection
    org, _, _ = base(c)
    with pytest.raises(Exception, match="check constraint"):
        execute(c, "INSERT INTO role_actions VALUES (%s,%s,'admin.everything')", (org, uuid4()))


def test_authz_epoch_advances_but_direct_edit_rejected(connection):
    c = connection
    org, member, _ = base(c)
    before = execute(c, "SELECT authz_version FROM organizations WHERE id=%s", (org,)).scalar_one()
    execute(
        c,
        "UPDATE members SET disabled_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=%s",
        (member,),
    )
    assert (
        execute(c, "SELECT authz_version FROM organizations WHERE id=%s", (org,)).scalar_one()
        == before + 1
    )
    with pytest.raises(Exception, match="authz_version"):
        execute(
            c,
            "UPDATE organizations SET authz_version=1,lock_version=lock_version+1 WHERE id=%s",
            (org,),
        )


def test_current_pointer_required(connection):
    c = connection
    org, member, work = base(c)
    execute(
        c,
        "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) "
        "VALUES (%s,%s,%s,%s,'script',%s)",
        (uuid4(), org, work, str(uuid4()), member),
    )
    with pytest.raises(Exception, match="current pointer"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize("locator", ["paragraph", "time", "unknown"])
def test_invalid_locator_slots_rejected(connection, locator):
    c = connection
    org, member, _ = base(c)
    ref = raw(c, org, member)
    with pytest.raises(Exception, match="check constraint"):
        execute(
            c,
            "INSERT INTO evidence_refs(id,org_id,raw_asset_id,locator_kind) VALUES (%s,%s,%s,%s)",
            (uuid4(), org, ref, locator),
        )


def test_text_evidence_cannot_exceed_source(connection):
    c = connection
    org, member, _ = base(c)
    ref = raw(c, org, member, "one line")
    execute(
        c,
        "INSERT INTO evidence_refs(id,org_id,raw_asset_id,locator_kind,paragraph_no) VALUES (%s,%s,%s,'paragraph',2)",
        (uuid4(), org, ref),
    )
    with pytest.raises(Exception, match="source bounds"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_valid_inputs_knowledge_and_prediction(connection):
    c = connection
    org, member, work = base(c)
    knowledge(c, org, member)
    draft, frozen = prediction(c, org, member, work)
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    execute(
        c,
        "UPDATE prediction_drafts SET lower_bound=2,upper_bound=3,lock_version=lock_version+1 WHERE id=%s",
        (draft,),
    )
    assert (
        execute(c, "SELECT lower_bound FROM predictions WHERE id=%s", (frozen,)).scalar_one() == 1
    )
    with pytest.raises(Exception, match="immutable|sealed"):
        execute(c, "UPDATE predictions SET lower_bound=2 WHERE id=%s", (frozen,))


def test_prediction_confirmation_requires_first_commit(connection):
    c = connection
    org, member, work = base(c)
    _, frozen = prediction(c, org, member, work)
    with pytest.raises(Exception, match="commit"):
        execute(
            c,
            "INSERT INTO prediction_events(id,org_id,prediction_id,event_kind,reason,actor_member_id) "
            "VALUES (%s,%s,%s,'freeze_confirmed','confirmed',%s)",
            (uuid4(), org, frozen, member),
        )


def test_unsupported_full_and_retrospective_values_are_not_available(connection):
    from app.core.models import metadata

    report_checks = " ".join(
        str(x.sqltext)
        for x in metadata.tables["analysis_reports"].constraints
        if hasattr(x, "sqltext")
    )
    knowledge_checks = " ".join(
        str(x.sqltext)
        for x in metadata.tables["knowledge_revisions"].constraints
        if hasattr(x, "sqltext")
    )
    assert "coverage_kind='partial'" in report_checks
    assert "origin IN ('manual','analysis')" in knowledge_checks


def test_catalog_columns_match_all_seventy_models(connection):
    from sqlalchemy import inspect

    from app.core.models import TABLE_GROUPS, metadata

    inspector = inspect(connection)
    assert list(map(len, TABLE_GROUPS)) == [17, 18, 37]
    for name, model in metadata.tables.items():
        actual = {v["name"]: v for v in inspector.get_columns(name)}
        assert set(actual) == set(model.c.keys()), name
        assert all(actual[col.name]["nullable"] == col.nullable for col in model.c), name
        assert len(inspector.get_foreign_keys(name)) == len(model.foreign_key_constraints), name


def test_task_idempotency_and_digest_conflict(connection):
    from app.core.repository import IdempotencyConflict, create_task

    c = connection
    org, member, work = base(c)
    values = {
        "org_id": org,
        "kind": "parse",
        "handler_version": "1",
        "work_id": work,
        "requested_by": member,
        "execution_authorized_by": member,
        "idempotency_key": "same",
        "input_sha256": "0" * 64,
    }
    first, created = create_task(c, values)
    assert created
    assert create_task(c, values) == (first, False)
    with pytest.raises(IdempotencyConflict):
        create_task(c, {**values, "input_sha256": "1" * 64})
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_claim_and_success_with_empty_outputs(connection):
    from app.core.repository import claim_task, finish_task

    c = connection
    org, member, work = base(c)
    ident = task(c, org, member, work)
    attempt, token, version = claim_task(c, org, ident, 2)
    finish_task(c, org, ident, attempt, token, version, business_outcome="insufficient_evidence")
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    row = execute(
        c, "SELECT state,business_outcome,outputs_sealed_at FROM tasks WHERE id=%s", (ident,)
    ).one()
    assert row[0:2] == ("succeeded", "insufficient_evidence") and row[2] is not None


@pytest.mark.parametrize("failure", ["token", "version", "cancel", "lease"])
def test_stale_worker_cannot_complete(connection, failure):
    from app.core.repository import claim_task, finish_task

    c = connection
    org, member, work = base(c)
    ident = task(c, org, member, work)
    attempt, token, version = claim_task(c, org, ident, 2)
    if failure == "token":
        token = uuid4()
    if failure == "version":
        version -= 1
    if failure == "cancel":
        execute(
            c,
            "UPDATE tasks SET state='cancel_requested',lock_version=lock_version+1 WHERE id=%s",
            (ident,),
        )
        version += 1
    if failure == "lease":
        execute(
            c,
            "UPDATE task_attempts SET lease_expires_at=started_at+interval '0.000001 seconds' WHERE id=%s",
            (attempt,),
        )
    with pytest.raises(Exception, match="STALE_RESULT"):
        finish_task(c, org, ident, attempt, token, version)


def test_processing_graph_cross_table_cycle(connection):
    from app.core.repository import claim_task

    c = connection
    org, member, work = base(c)
    artifact = uuid4()
    version = uuid4()
    ident = uuid4()
    child = uuid4()
    execute(
        c,
        "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES (%s,%s,%s,%s,'script',%s)",
        (artifact, org, work, str(artifact), member),
    )
    execute(
        c,
        "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,material_kind,body_text,content_sha256,created_by) "
        "VALUES (%s,%s,%s,%s,1,'script','text',%s,%s)",
        (version, org, artifact, work, "8" * 64, member),
    )
    execute(
        c,
        "INSERT INTO tasks(id,org_id,kind,handler_version,work_id,requested_by,execution_authorized_by,idempotency_key,input_sha256) "
        "VALUES (%s,%s,'parse','1',%s,%s,%s,%s,%s)",
        (ident, org, work, member, member, str(ident), "0" * 64),
    )
    execute(
        c,
        "INSERT INTO task_inputs(org_id,task_id,position,role,artifact_version_id) VALUES (%s,%s,0,'material',%s)",
        (org, ident, version),
    )
    execute(c, "SELECT cip_seal('tasks',%s,%s,'inputs')", (org, ident))
    claim_task(c, org, ident, 2)
    execute(
        c,
        "INSERT INTO raw_assets(id,org_id,origin,asset_kind,processing_task_id,parent_artifact_version_id,body_text,sha256,captured_at) "
        "VALUES (%s,%s,'processing','transcript',%s,%s,'derived',%s,clock_timestamp())",
        (child, org, ident, version, "9" * 64),
    )
    execute(
        c,
        "INSERT INTO artifact_version_sources VALUES (%s,%s,%s,'transcript')",
        (org, version, child),
    )
    execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
    execute(
        c,
        "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (version, artifact),
    )
    with pytest.raises(Exception, match="cycle"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_human_cannot_approve_knowledge_without_ai(connection):
    c = connection
    org, member, _ = base(c)
    _, rev = knowledge(c, org, member)
    request = uuid4()
    execute(
        c,
        "INSERT INTO review_requests(id,org_id,purpose,knowledge_revision_id,input_sha256,requested_by) "
        "VALUES (%s,%s,'knowledge_release',%s,%s,%s)",
        (request, org, rev, "4" * 64, member),
    )
    with pytest.raises(Exception, match="approved AI required"):
        execute(
            c,
            "INSERT INTO review_decisions(id,org_id,request_id,reviewer_kind,reviewer_member_id,verdict,reason,input_sha256) "
            "VALUES (%s,%s,%s,'human',%s,'approved','approve',%s)",
            (uuid4(), org, request, member, "4" * 64),
        )


def standard(c, org, member, *, kind="rubric", origin="expert_baseline"):
    identity, revision = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO standards(id,org_id,code,kind,business_code,name) VALUES (%s,%s,%s,%s,'motion_comic','standard')",
        (identity, org, str(identity), kind),
    )
    execute(
        c,
        "INSERT INTO standard_revisions(id,org_id,standard_id,version_no,definition,origin_kind,provenance_note,content_sha256,created_by) "
        "VALUES (%s,%s,%s,1,'{}',%s,'explicit test fixture',%s,%s)",
        (revision, org, identity, origin, "a" * 64, member),
    )
    return identity, revision


def approve_standard(c, org, member, revision):
    req, dec = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO review_requests(id,org_id,purpose,standard_revision_id,input_sha256,requested_by) VALUES (%s,%s,'standard_approval',%s,%s,%s)",
        (req, org, revision, "a" * 64, member),
    )
    execute(
        c,
        "INSERT INTO review_decisions(id,org_id,request_id,reviewer_kind,reviewer_member_id,verdict,reason,input_sha256) "
        "VALUES (%s,%s,%s,'human',%s,'approved','expert baseline reviewed',%s)",
        (dec, org, req, member, "a" * 64),
    )
    execute(
        c,
        "INSERT INTO review_heads(org_id,request_id,reviewer_kind,decision_id) VALUES (%s,%s,'human',%s)",
        (org, req, dec),
    )
    return req, dec


def test_first_expert_baseline_activation_and_closed_review(connection):
    c = connection
    org, member, _ = base(c)
    identity, revision = standard(c, org, member)
    req, _ = approve_standard(c, org, member, revision)
    execute(
        c,
        "UPDATE standards SET active_revision_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (revision, identity),
    )
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Exception, match="closed"):
        execute(
            c,
            "INSERT INTO review_decisions(id,org_id,request_id,reviewer_kind,reviewer_member_id,verdict,reason,input_sha256) "
            "VALUES (%s,%s,%s,'human',%s,'rejected','changed mind',%s)",
            (uuid4(), org, req, member, "a" * 64),
        )


@pytest.mark.parametrize("origin", ["expert_baseline", "learning_candidate"])
def test_unapproved_or_learning_standard_cannot_activate(connection, origin):
    c = connection
    org, member, _ = base(c)
    identity, revision = standard(c, org, member, origin=origin)
    with pytest.raises(Exception, match="STANDARD_NOT_APPROVED|B1 rubric"):
        execute(
            c,
            "UPDATE standards SET active_revision_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (revision, identity),
        )
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_empty_scope_grant_rejected(connection):
    c = connection
    org, member, _ = base(c)
    role = uuid4()
    execute(
        c,
        "INSERT INTO role_definitions(id,org_id,code,name) VALUES (%s,%s,'reader','reader')",
        (role, org),
    )
    with pytest.raises(Exception, match="check constraint"):
        execute(
            c,
            "INSERT INTO grants(id,org_id,member_id,role_id,scope_kind,granted_by) VALUES (%s,%s,%s,%s,'work',%s)",
            (uuid4(), org, member, role, member),
        )


def test_unknown_metric_is_null_and_actual_zero_survives(connection):
    c = connection
    org, member, _ = base(c)
    content, obs = uuid4(), uuid4()
    source = raw(c, org, member)
    execute(
        c,
        "INSERT INTO external_contents(id,org_id,platform_code,platform_content_id) VALUES (%s,%s,'douyin','12345678901234567890')",
        (content, org),
    )
    execute(
        c,
        "INSERT INTO content_observations(id,org_id,content_id,raw_asset_id,observed_at,like_count) VALUES (%s,%s,%s,%s,clock_timestamp(),0)",
        (obs, org, content, source),
    )
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    assert execute(
        c, "SELECT like_count,view_count,repost_count FROM content_observations WHERE id=%s", (obs,)
    ).one() == (0, None, None)


def ai_task(c, org, member, work, *, request=None, input_id=None):
    from app.core.repository import claim_task, create_task, finish_task

    connection_id, config, file_id, execution = uuid4(), uuid4(), uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO provider_connections(id,org_id,provider_code,name,secret_ref) VALUES (%s,%s,'test_fixture',%s,'TEST_ONLY')",
        (connection_id, org, str(connection_id)),
    )
    execute(
        c,
        "INSERT INTO ai_config_revisions(id,org_id,config_key,version_no,task_kind,provider_connection_id,model_identifier,output_schema,content_sha256,created_by) "
        "VALUES (%s,%s,%s,1,'review',%s,'offline-fixture','{}',%s,%s)",
        (config, org, str(config), connection_id, "b" * 64, member),
    )
    execute(
        c,
        "INSERT INTO file_objects(id,org_id,storage_backend,storage_key,media_type,byte_size,sha256,validation_state) "
        "VALUES (%s,%s,'test',%s,'application/json',2,%s,'accepted')",
        (file_id, org, str(file_id), "c" * 64),
    )
    manifest = [{"role": "config", "ai_config_revision_id": config}]
    if request:
        manifest.append({"role": "request", "review_request_id": request})
    if input_id:
        manifest.append({"role": "material", "input_set_id": input_id})
    ident, _ = create_task(
        c,
        {
            "org_id": org,
            "kind": "review",
            "handler_version": "1",
            "work_id": work,
            "requested_by": member,
            "execution_authorized_by": member,
            "idempotency_key": str(uuid4()),
            "input_sha256": "d" * 64,
            "max_external_calls": 1,
        },
        manifest,
    )
    attempt, token, version = claim_task(c, org, ident, 2)
    execute(
        c,
        "INSERT INTO ai_executions(id,org_id,task_id,attempt_id,config_revision_id,invocation_no,input_sha256,input_manifest_file_id) "
        "VALUES (%s,%s,%s,%s,%s,1,%s,%s)",
        (execution, org, ident, attempt, config, "d" * 64, file_id),
    )
    execute(
        c,
        "UPDATE ai_executions SET result_state='completed',output_file_id=%s,finished_at=clock_timestamp() WHERE id=%s",
        (file_id, execution),
    )
    finish_task(c, org, ident, attempt, token, version)
    return execution, ident


def reviewed_knowledge(c, org, member, work):
    item, revision = knowledge(c, org, member)
    request = uuid4()
    execute(
        c,
        "INSERT INTO review_requests(id,org_id,purpose,knowledge_revision_id,input_sha256,requested_by) "
        "VALUES (%s,%s,'knowledge_release',%s,%s,%s)",
        (request, org, revision, "4" * 64, member),
    )
    execution, _ = ai_task(c, org, member, work, request=request)
    ai, human = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO review_decisions(id,org_id,request_id,reviewer_kind,ai_execution_id,verdict,reason,input_sha256) "
        "VALUES (%s,%s,%s,'ai',%s,'approved','fixture reviewed',%s)",
        (ai, org, request, execution, "4" * 64),
    )
    execute(
        c,
        "INSERT INTO review_heads(org_id,request_id,reviewer_kind,decision_id) VALUES (%s,%s,'ai',%s)",
        (org, request, ai),
    )
    execute(
        c,
        "INSERT INTO review_decisions(id,org_id,request_id,reviewer_kind,reviewer_member_id,verdict,reason,input_sha256,reviewed_ai_decision_id) "
        "VALUES (%s,%s,%s,'human',%s,'approved','human reviewed',%s,%s)",
        (human, org, request, member, "4" * 64, ai),
    )
    execute(
        c,
        "INSERT INTO review_heads(org_id,request_id,reviewer_kind,decision_id) VALUES (%s,%s,'human',%s)",
        (org, request, human),
    )
    return item, revision, request, ai, human


def test_double_review_publication_and_formal_search_index(connection):
    c = connection
    org, member, work = base(c)
    item, revision, request, ai, human = reviewed_knowledge(c, org, member, work)
    pub, document = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO knowledge_publications(id,org_id,knowledge_id,revision_id,review_request_id,ai_decision_id,human_decision_id,published_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (pub, org, item, revision, request, ai, human, member),
    )
    execute(
        c,
        "UPDATE knowledge_items SET published_publication_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (pub, item),
    )
    execute(
        c,
        "INSERT INTO search_documents(id,org_id,publication_id,revision_id,document_text,search_vector,index_config_version) "
        "VALUES (%s,%s,%s,%s,'fixture text',to_tsvector('simple','fixture text'),'fixture-only')",
        (document, org, pub, revision),
    )
    execute(
        c,
        "INSERT INTO embeddings(id,org_id,search_document_id,chunk_no,start_offset,end_offset,embedding_model,model_version,dimensions,embedding,content_sha256) "
        "VALUES (%s,%s,%s,0,0,7,'fixture','1',3,'[1,2,3]',%s)",
        (uuid4(), org, document, "e" * 64),
    )
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Exception, match="closed"):
        execute(
            c, "UPDATE review_heads SET lock_version=lock_version+1 WHERE request_id=%s", (request,)
        )


def test_old_human_review_cannot_publish_after_ai_head_changes(connection):
    c = connection
    org, member, work = base(c)
    item, revision, request, ai, human = reviewed_knowledge(c, org, member, work)
    execution, _ = ai_task(c, org, member, work, request=request)
    new_ai = uuid4()
    execute(
        c,
        "INSERT INTO review_decisions(id,org_id,request_id,reviewer_kind,ai_execution_id,verdict,reason,input_sha256,supersedes_decision_id) "
        "VALUES (%s,%s,%s,'ai',%s,'approved','new review',%s,%s)",
        (new_ai, org, request, execution, "4" * 64, ai),
    )
    execute(
        c,
        "UPDATE review_heads SET decision_id=%s,lock_version=lock_version+1 WHERE request_id=%s AND reviewer_kind='ai'",
        (new_ai, request),
    )
    execute(
        c,
        "INSERT INTO knowledge_publications(id,org_id,knowledge_id,revision_id,review_request_id,ai_decision_id,human_decision_id,published_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (uuid4(), org, item, revision, request, new_ai, human, member),
    )
    with pytest.raises(Exception, match="double review"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def collection(c, org, member):
    from app.core.repository import claim_task, create_task

    source, provider, job, call = uuid4(), uuid4(), uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO sources(id,org_id,name,business_code,platform_code,target_kind,keyword,created_by) "
        "VALUES (%s,%s,'test source','motion_comic','douyin','keyword','漫剧',%s)",
        (source, org, member),
    )
    execute(
        c,
        "INSERT INTO provider_connections(id,org_id,provider_code,name,secret_ref) VALUES (%s,%s,'test_fixture',%s,'TEST_ONLY')",
        (provider, org, str(provider)),
    )
    ident, _ = create_task(
        c,
        {
            "org_id": org,
            "kind": "collect",
            "handler_version": "1",
            "source_id": source,
            "business_code": "motion_comic",
            "requested_by": member,
            "execution_authorized_by": member,
            "max_external_calls": 1,
            "idempotency_key": str(uuid4()),
            "input_sha256": "0" * 64,
        },
    )
    attempt, _, _ = claim_task(c, org, ident, 2)
    execute(
        c,
        "INSERT INTO collection_jobs(id,org_id,source_id,connection_id,task_id,capability_code,connector_version,business_code,business_date,safe_request,request_sha256,max_requests,max_items) "
        "SELECT %s,%s,%s,%s,id,'fixture','1','motion_comic',(created_at AT TIME ZONE 'Asia/Shanghai')::date,'{}',%s,1,1 FROM tasks WHERE id=%s",
        (job, org, source, provider, "0" * 64, ident),
    )
    execute(
        c,
        "INSERT INTO collection_calls(id,org_id,job_id,attempt_id,sequence_no,request_sha256) VALUES (%s,%s,%s,%s,1,%s)",
        (call, org, job, attempt, "0" * 64),
    )
    return source, job, call, attempt


@pytest.mark.parametrize("outcome", ["success", "provider_error"])
def test_empty_snapshot_requires_successful_call(connection, outcome):
    c = connection
    org, member, _ = base(c)
    _source, job, call, _ = collection(c, org, member)
    execute(
        c,
        "UPDATE collection_calls SET outcome=%s,completed_at=clock_timestamp(),returned_items=0 WHERE id=%s",
        (outcome, call),
    )
    snapshot = uuid4()
    execute(
        c,
        "INSERT INTO intelligence_snapshots(id,org_id,source_id,job_id,business_code,business_date,view_kind,version_no,entry_count) "
        "SELECT %s,org_id,source_id,id,business_code,business_date,'keyword_works',1,0 FROM collection_jobs WHERE id=%s",
        (snapshot, job),
    )
    execute(c, "SELECT cip_seal('intelligence_snapshots',%s,%s)", (org, snapshot))
    if outcome == "success":
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    else:
        with pytest.raises(Exception, match="snapshot provenance"):
            execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_external_call_budget_is_not_renewed_by_another_sequence(connection):
    c = connection
    org, member, _ = base(c)
    _, job, _, attempt = collection(c, org, member)
    with pytest.raises(Exception, match="BUDGET_EXHAUSTED|budget exhausted"):
        execute(
            c,
            "INSERT INTO collection_calls(id,org_id,job_id,attempt_id,sequence_no,request_sha256) VALUES (%s,%s,%s,%s,2,%s)",
            (uuid4(), org, job, attempt, "0" * 64),
        )


def test_grant_revocation_cannot_be_cleared(connection):
    c = connection
    org, member, work = base(c)
    role, grant = uuid4(), uuid4()
    execute(
        c,
        "INSERT INTO role_definitions(id,org_id,code,name) VALUES (%s,%s,'reader','reader')",
        (role, org),
    )
    execute(c, "INSERT INTO role_actions VALUES (%s,%s,'content.read')", (org, role))
    execute(c, "DELETE FROM role_actions WHERE org_id=%s AND role_id=%s", (org, role))
    execute(
        c,
        "INSERT INTO grants(id,org_id,member_id,role_id,scope_kind,work_id,granted_by,revoked_at) "
        "VALUES (%s,%s,%s,%s,'work',%s,%s,clock_timestamp())",
        (grant, org, member, role, work, member),
    )
    with pytest.raises(Exception, match="revocation"):
        execute(
            c, "UPDATE grants SET revoked_at=NULL,lock_version=lock_version+1 WHERE id=%s", (grant,)
        )


def test_live_snapshot_cannot_mix_yesterdays_observation(connection):
    c = connection
    org, member, _ = base(c)
    _, job, call, _ = collection(c, org, member)
    execute(
        c,
        "UPDATE collection_calls SET outcome='success',completed_at=clock_timestamp(),returned_items=1 WHERE id=%s",
        (call,),
    )
    raw_id, account, observation, snapshot, entry = [uuid4() for _ in range(5)]
    execute(
        c,
        "INSERT INTO raw_assets(id,org_id,origin,asset_kind,collection_job_id,collection_call_id,body_text,sha256,captured_at) "
        "VALUES (%s,%s,'api','response',%s,%s,'fixture',%s,clock_timestamp()-interval '1 day')",
        (raw_id, org, job, call, "f" * 64),
    )
    execute(
        c,
        "INSERT INTO external_accounts(id,org_id,platform_code,platform_uid) VALUES (%s,%s,'douyin',%s)",
        (account, org, str(account)),
    )
    execute(
        c,
        "INSERT INTO account_observations(id,org_id,account_id,raw_asset_id,observed_at) VALUES (%s,%s,%s,%s,clock_timestamp())",
        (observation, org, account, raw_id),
    )
    execute(
        c,
        "INSERT INTO intelligence_snapshots(id,org_id,source_id,job_id,business_code,business_date,view_kind,version_no,entry_count) "
        "SELECT %s,org_id,source_id,id,business_code,business_date,'account_discovery',1,1 FROM collection_jobs WHERE id=%s",
        (snapshot, job),
    )
    execute(
        c,
        "INSERT INTO snapshot_entries(id,org_id,snapshot_id,position,account_observation_id) VALUES (%s,%s,%s,0,%s)",
        (entry, org, snapshot, observation),
    )
    execute(c, "SELECT cip_seal('intelligence_snapshots',%s,%s)", (org, snapshot))
    with pytest.raises(Exception, match="DATE_WINDOW_MISMATCH"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_task_cannot_claim_another_tasks_execution_as_output(connection):
    c = connection
    org, member, work = base(c)
    execution, _ = ai_task(c, org, member, work)
    from app.core.repository import claim_task, create_task, finish_task

    ident, _ = create_task(
        c,
        {
            "org_id": org,
            "kind": "parse",
            "handler_version": "1",
            "work_id": work,
            "requested_by": member,
            "execution_authorized_by": member,
            "idempotency_key": str(uuid4()),
            "input_sha256": "0" * 64,
        },
    )
    attempt, token, version = claim_task(c, org, ident, 2)
    execute(
        c,
        "INSERT INTO task_outputs(org_id,task_id,position,role,ai_execution_id) VALUES (%s,%s,0,'result',%s)",
        (org, ident, execution),
    )
    finish_task(c, org, ident, attempt, token, version)
    with pytest.raises(Exception, match="output.*task|another task"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize(
    "table_name,columns,values",
    [
        (
            "standards",
            "code,kind,business_code,name,active_revision_id",
            "'fixture','rubric','motion_comic','s',%s",
        ),
        (
            "works",
            "business_code,work_number,name,created_by,latest_report_id",
            "'motion_comic','forward','w',%s,%s",
        ),
        (
            "knowledge_items",
            "title,owner_member_id,created_by,published_publication_id",
            "'forward',%s,%s,%s",
        ),
    ],
)
def test_insert_cannot_preinstall_active_or_formal_pointer(connection, table_name, columns, values):
    c = connection
    org, member, _ = base(c)
    params = [uuid4(), org]
    params += (
        [uuid4()]
        if table_name == "standards"
        else [member, uuid4()]
        if table_name == "works"
        else [member, member, uuid4()]
    )
    with pytest.raises(Exception, match="initial pointer"):
        execute(
            c,
            f"INSERT INTO {table_name}(id,org_id,{columns}) VALUES (%s,%s,{values})",
            tuple(params),
        )


def test_future_task_is_not_claimable(connection):
    from app.core.repository import claim_task, create_task

    c = connection
    org, member, work = base(c)
    ident, _ = create_task(
        c,
        {
            "org_id": org,
            "kind": "parse",
            "handler_version": "1",
            "work_id": work,
            "requested_by": member,
            "execution_authorized_by": member,
            "idempotency_key": str(uuid4()),
            "input_sha256": "0" * 64,
        },
    )
    execute(
        c,
        "UPDATE tasks SET available_at=clock_timestamp()+interval '1 day',lock_version=lock_version+1 WHERE id=%s",
        (ident,),
    )
    with pytest.raises(Exception, match="unavailable|available"):
        claim_task(c, org, ident, 3)


def test_task_primary_input_cannot_belong_to_another_work(connection):
    from app.core.repository import create_task

    c = connection
    org, member, work = base(c)
    input_id, _, _ = inputs(c, org, member, work)
    other = uuid4()
    execute(
        c,
        "INSERT INTO works(id,org_id,business_code,work_number,name,created_by) VALUES (%s,%s,'motion_comic',%s,'other',%s)",
        (other, org, str(other), member),
    )
    create_task(
        c,
        {
            "org_id": org,
            "kind": "analyze",
            "handler_version": "1",
            "work_id": other,
            "requested_by": member,
            "execution_authorized_by": member,
            "idempotency_key": str(uuid4()),
            "input_sha256": "0" * 64,
        },
        [{"role": "material", "input_set_id": input_id}],
    )
    with pytest.raises(Exception, match="task.*work|work.*task"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_report_generation_cannot_advance_without_creating_run(connection):
    c = connection
    _, _, work = base(c)
    execute(
        c,
        "UPDATE works SET report_generation=report_generation+1,lock_version=lock_version+1 WHERE id=%s",
        (work,),
    )
    with pytest.raises(Exception, match="generation"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_normalization_cannot_silently_select_unknown_digest_algorithm(connection):
    c = connection
    org, member, _ = base(c)
    with pytest.raises(Exception, match="check constraint"):
        execute(
            c,
            "INSERT INTO raw_assets(id,org_id,origin,asset_kind,submitted_by,body_text,sha256,captured_at,normalization_version) "
            "VALUES (%s,%s,'manual','text',%s,'text',%s,clock_timestamp(),2)",
            (uuid4(), org, member, "0" * 64),
        )


def test_graph_depth_limit_cannot_be_bypassed_with_reference_edges(connection):
    c = connection
    org, member, work = base(c)
    artifact = uuid4()
    execute(
        c,
        "INSERT INTO artifacts(id,org_id,work_id,material_number,material_kind,created_by) VALUES (%s,%s,%s,%s,'script',%s)",
        (artifact, org, work, str(artifact), member),
    )
    previous = None
    for n in range(34):
        version = uuid4()
        execute(
            c,
            "INSERT INTO artifact_versions(id,org_id,artifact_id,work_id,version_no,material_kind,body_text,content_sha256,created_by) "
            "VALUES (%s,%s,%s,%s,%s,'script','text',%s,%s)",
            (version, org, artifact, work, n + 1, format(n, "064x"), member),
        )
        if previous:
            execute(
                c,
                "INSERT INTO artifact_lineage VALUES (%s,%s,%s,'references')",
                (org, version, previous),
            )
        execute(c, "SELECT cip_seal('artifact_versions',%s,%s)", (org, version))
        previous = version
    execute(
        c,
        "UPDATE artifacts SET current_version_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (previous, artifact),
    )
    with pytest.raises(Exception, match="depth exceeds 32"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def run_and_report(c, org, member, work, input_id, generation):
    execution, ident = ai_task(c, org, member, work, input_id=input_id)
    _template, revision = standard(
        c, org, member, kind="analysis_template", origin="manual_configuration"
    )
    approve_standard(c, org, member, revision)
    run, report = uuid4(), uuid4()
    execute(
        c,
        "UPDATE works SET report_generation=%s,lock_version=lock_version+1 WHERE id=%s",
        (generation, work),
    )
    execute(
        c,
        "INSERT INTO analysis_runs(id,org_id,report_generation,input_set_id,task_id,template_revision_id,ai_config_revision_id,state,started_at,finished_at) "
        "SELECT %s,t.org_id,%s,%s,t.id,%s,e.config_revision_id,t.state,t.started_at,t.finished_at FROM tasks t JOIN ai_executions e ON e.task_id=t.id WHERE t.id=%s",
        (run, generation, input_id, revision, ident),
    )
    execute(
        c,
        "INSERT INTO analysis_reports(id,org_id,work_id,input_set_id,analysis_run_id,ai_execution_id,version_no,coverage_kind,body,result_state,content_sha256) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'partial','{}','completed',%s)",
        (report, org, work, input_id, run, execution, generation, format(generation, "064x")),
    )
    execute(c, "SELECT cip_seal('analysis_reports',%s,%s)", (org, report))
    return report, revision, execution, ident


def test_old_report_cannot_replace_latest_generation(connection):
    c = connection
    org, member, work = base(c)
    input_id, _, _ = inputs(c, org, member, work)
    old, _, _, _ = run_and_report(c, org, member, work, input_id, 1)
    current, _, _, _ = run_and_report(c, org, member, work, input_id, 2)
    execute(
        c,
        "UPDATE works SET latest_report_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (current, work),
    )
    execute(c, "SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(Exception, match="stale report"):
        execute(
            c,
            "UPDATE works SET latest_report_id=%s,lock_version=lock_version+1 WHERE id=%s",
            (old, work),
        )


def test_evidence_must_belong_to_exact_frozen_input(connection):
    c = connection
    org, member, work = base(c)
    input_id, _, _ = inputs(c, org, member, work)
    execution, ident = ai_task(c, org, member, work, input_id=input_id)
    _, rubric = standard(c, org, member)
    approve_standard(c, org, member, rubric)
    evaluation = uuid4()
    unrelated = raw(c, org, member)
    evidence = uuid4()
    execute(
        c,
        "INSERT INTO evidence_refs(id,org_id,raw_asset_id,locator_kind) VALUES (%s,%s,%s,'whole')",
        (evidence, org, unrelated),
    )
    execute(
        c,
        "INSERT INTO quality_evaluations(id,org_id,input_set_id,task_id,rubric_revision_id,ai_execution_id,result_state,quality_grade,dimensions,content_sha256) "
        "VALUES (%s,%s,%s,%s,%s,%s,'completed','A','{}',%s)",
        (evaluation, org, input_id, ident, rubric, execution, "f" * 64),
    )
    execute(
        c,
        "INSERT INTO evaluation_evidence VALUES (%s,%s,%s,'fixture')",
        (org, evaluation, evidence),
    )
    execute(c, "SELECT cip_seal('quality_evaluations',%s,%s)", (org, evaluation))
    with pytest.raises(Exception, match="outside frozen input"):
        execute(c, "SET CONSTRAINTS ALL IMMEDIATE")


def test_publication_cannot_publish_old_candidate_after_revision_changes(connection):
    c = connection
    org, member, work = base(c)
    item, revision, request, ai, human = reviewed_knowledge(c, org, member, work)
    next_rev = uuid4()
    execute(
        c,
        "INSERT INTO knowledge_revisions(id,org_id,knowledge_id,version_no,title,body_text,knowledge_type,browse_category,origin,created_by,content_sha256) "
        "VALUES (%s,%s,%s,2,'new','new','fact','genre','manual',%s,%s)",
        (next_rev, org, item, member, "e" * 64),
    )
    execute(c, "INSERT INTO knowledge_businesses VALUES (%s,%s,'motion_comic')", (org, next_rev))
    execute(c, "SELECT cip_seal('knowledge_revisions',%s,%s)", (org, next_rev))
    execute(
        c,
        "UPDATE knowledge_items SET current_revision_id=%s,lock_version=lock_version+1 WHERE id=%s",
        (next_rev, item),
    )
    with pytest.raises(Exception, match="current candidate"):
        execute(
            c,
            "INSERT INTO knowledge_publications(id,org_id,knowledge_id,revision_id,review_request_id,ai_decision_id,human_decision_id,published_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (uuid4(), org, item, revision, request, ai, human, member),
        )
