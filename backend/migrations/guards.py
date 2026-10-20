"""Build initial frozen guard SQL. Not imported by migration revisions."""

from app.core.models import MUTABLE, SEALED, metadata

CHILDREN = {
    "artifact_version_sources": ("artifact_versions", "artifact_version_id", "sealed_at"),
    "artifact_version_units": ("artifact_versions", "artifact_version_id", "sealed_at"),
    "artifact_lineage": ("artifact_versions", "from_version_id", "sealed_at"),
    "preliminary_assessments": ("research_submissions", "submission_id", "sealed_at"),
    "input_set_items": ("input_sets", "input_set_id", "sealed_at"),
    "report_units": ("analysis_reports", "report_id", "sealed_at"),
    "report_evidence": ("analysis_reports", "report_id", "sealed_at"),
    "evaluation_evidence": ("quality_evaluations", "evaluation_id", "sealed_at"),
    "feedback_comments": ("feedback_snapshots", "feedback_id", "sealed_at"),
    "feedback_claims": ("feedback_snapshots", "feedback_id", "sealed_at"),
    "feedback_claim_evidence": ("feedback_snapshots", "feedback_id", "sealed_at"),
    "knowledge_businesses": ("knowledge_revisions", "revision_id", "sealed_at"),
    "knowledge_evidence": ("knowledge_revisions", "revision_id", "sealed_at"),
    "knowledge_relations": ("knowledge_revisions", "from_revision_id", "sealed_at"),
    "prediction_evidence": ("predictions", "prediction_id", "sealed_at"),
    "snapshot_entries": ("intelligence_snapshots", "snapshot_id", "sealed_at"),
    "task_inputs": ("tasks", "task_id", "inputs_sealed_at"),
    "task_outputs": ("tasks", "task_id", "outputs_sealed_at"),
}

HEADER = r"""
-- S04 integrity guards. All functions use fixed search_path, invoker rights.
CREATE FUNCTION cip_parent_open() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE row_data jsonb; stamp timestamptz; parent_id uuid;
BEGIN
 row_data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 parent_id := (row_data->>TG_ARGV[1])::uuid;
 EXECUTE format('SELECT %I FROM %I WHERE org_id=$1 AND id=$2 FOR UPDATE',TG_ARGV[2],TG_ARGV[0])
   INTO stamp USING (row_data->>'org_id')::uuid,parent_id;
 IF NOT FOUND THEN
   -- EXECUTE does not set FOUND; presence is checked by FK at commit.
   NULL;
 END IF;
 IF stamp IS NOT NULL THEN RAISE EXCEPTION 'sealed parent collection is immutable'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cip_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE allowed text[]; old_body jsonb; new_body jsonb;
BEGIN
 IF TG_OP='DELETE' THEN
   IF TG_TABLE_NAME='role_actions' THEN RETURN OLD; END IF;
   RAISE EXCEPTION 'immutable record cannot be deleted'; END IF;
 allowed := string_to_array(TG_ARGV[0],',');
 old_body := to_jsonb(OLD); new_body := to_jsonb(NEW);
 IF TG_ARGV[1]='sealed' THEN
   IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL THEN
      RAISE EXCEPTION 'sealed record is immutable';
   END IF;
   NEW.sealed_at := clock_timestamp();
 END IF;
 IF (old_body-allowed) IS DISTINCT FROM (new_body-allowed) THEN
    RAISE EXCEPTION 'immutable fields cannot change in %',TG_TABLE_NAME;
 END IF;
 IF old_body ? 'lock_version' THEN
   IF (new_body->>'lock_version')::bigint<>(old_body->>'lock_version')::bigint+1 THEN
      RAISE EXCEPTION 'VERSION_CONFLICT: lock_version must advance once';
   END IF;
   NEW.updated_at := clock_timestamp();
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cip_seal(target text, organization uuid, identity uuid, kind text DEFAULT 'sealed')
RETURNS void LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE column_name text; current_stamp timestamptz;
BEGIN
 IF target NOT IN (__SEALED__,'tasks') THEN RAISE EXCEPTION 'unsupported seal target'; END IF;
 column_name := CASE WHEN target='tasks' AND kind='inputs' THEN 'inputs_sealed_at'
                     WHEN target='tasks' AND kind='outputs' THEN 'outputs_sealed_at'
                     WHEN target<>'tasks' AND kind='sealed' THEN 'sealed_at' ELSE NULL END;
 IF column_name IS NULL THEN RAISE EXCEPTION 'invalid seal kind'; END IF;
 EXECUTE format('SELECT %I FROM %I WHERE org_id=$1 AND id=$2 FOR UPDATE',column_name,target)
 INTO current_stamp USING organization,identity;
 IF current_stamp IS NOT NULL THEN RAISE EXCEPTION 'already sealed'; END IF;
 EXECUTE format('UPDATE %I SET %I=clock_timestamp()%s WHERE org_id=$1 AND id=$2',
  target,column_name,CASE WHEN target='tasks' THEN ',lock_version=lock_version+1' ELSE '' END)
 USING organization,identity;
 IF NOT FOUND THEN NULL; END IF;
END $$;

CREATE FUNCTION cip_task_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'queued' OR NEW.inputs_frozen_at IS NOT NULL OR NEW.outputs_sealed_at IS NOT NULL
     OR NEW.started_at IS NOT NULL THEN RAISE EXCEPTION 'task must start queued'; END IF;
  IF NEW.requested_by IS NULL AND (NEW.kind<>'maintenance' OR NEW.max_external_calls<>0) THEN
     RAISE EXCEPTION 'business task requires requested_by'; END IF;
  NEW.inputs_sealed_at:=NULL;
  RETURN NEW;
 END IF;
 IF OLD.inputs_sealed_at IS NOT NULL AND NEW.inputs_sealed_at IS DISTINCT FROM OLD.inputs_sealed_at THEN
    RAISE EXCEPTION 'task inputs sealed'; END IF;
 IF OLD.outputs_sealed_at IS NOT NULL AND NEW.outputs_sealed_at IS DISTINCT FROM OLD.outputs_sealed_at THEN
    RAISE EXCEPTION 'task outputs sealed'; END IF;
 IF OLD.inputs_frozen_at IS NOT NULL AND
    (NEW.inputs_frozen_at IS DISTINCT FROM OLD.inputs_frozen_at OR
     NEW.execution_authorized_by IS DISTINCT FROM OLD.execution_authorized_by) THEN
    RAISE EXCEPTION 'task execution inputs frozen'; END IF;
 IF NEW.state<>OLD.state AND NOT (
    (OLD.state='queued' AND NEW.state IN ('running','failed','cancelled')) OR
    (OLD.state='running' AND NEW.state IN ('succeeded','failed','cancel_requested')) OR
    (OLD.state='cancel_requested' AND NEW.state IN ('cancelled','failed')) OR
    (OLD.state='failed' AND NEW.state='queued')) THEN
    RAISE EXCEPTION 'illegal task state transition'; END IF;
 IF NEW.state='running' AND OLD.state='queued' THEN
    IF NEW.execution_authorized_by IS NULL THEN RAISE EXCEPTION 'execution authorization required'; END IF;
    NEW.inputs_frozen_at:=COALESCE(OLD.inputs_frozen_at,clock_timestamp());
    NEW.started_at:=clock_timestamp();
 END IF;
 IF NEW.state='cancel_requested' AND OLD.state<>NEW.state THEN NEW.cancel_requested_at:=clock_timestamp(); END IF;
 IF NEW.inputs_sealed_at IS DISTINCT FROM OLD.inputs_sealed_at THEN NEW.inputs_sealed_at:=clock_timestamp(); END IF;
 IF NEW.outputs_sealed_at IS DISTINCT FROM OLD.outputs_sealed_at THEN NEW.outputs_sealed_at:=clock_timestamp(); END IF;
 IF NEW.state='queued' AND OLD.state='failed' AND (
    EXISTS(SELECT 1 FROM task_attempts WHERE task_id=NEW.id AND finished_at IS NULL) OR
    (SELECT count(*) FROM task_attempts WHERE task_id=NEW.id)>=NEW.max_attempts OR
    OLD.safe_error_code IN ('EXTERNAL_RESULT_UNKNOWN','CANCEL_UNCONFIRMED')) THEN
    RAISE EXCEPTION 'retry not safe or attempt budget exhausted'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cip_new_seal() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'create unsealed then seal in same transaction'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cip_runtime_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE t tasks; j collection_jobs; a task_attempts; n bigint; request_id uuid;
BEGIN
 IF TG_TABLE_NAME='task_attempts' THEN
   SELECT * INTO t FROM tasks WHERE id=NEW.task_id FOR UPDATE;
   IF TG_OP='INSERT' THEN
     IF t.state<>'running' OR NEW.attempt_no<>(SELECT count(*)+1 FROM task_attempts WHERE task_id=t.id)
       OR NEW.attempt_no>t.max_attempts THEN RAISE EXCEPTION 'invalid attempt state or budget'; END IF;
   ELSIF OLD.finished_at IS NOT NULL THEN RAISE EXCEPTION 'finished attempt immutable';
   ELSIF NEW.lease_expires_at<>OLD.lease_expires_at AND OLD.lease_expires_at<=clock_timestamp() THEN
      RAISE EXCEPTION 'lease lost';
   END IF;
 ELSIF TG_TABLE_NAME IN ('collection_calls','ai_executions') THEN
   IF TG_TABLE_NAME='collection_calls' THEN
     SELECT * INTO j FROM collection_jobs WHERE id=NEW.job_id;
     request_id:=j.task_id;
   ELSE request_id:=NEW.task_id;
   END IF;
   SELECT * INTO t FROM tasks WHERE id=request_id FOR UPDATE;
   SELECT * INTO a FROM task_attempts WHERE id=NEW.attempt_id FOR UPDATE;
   IF a.task_id IS DISTINCT FROM t.id THEN RAISE EXCEPTION 'attempt belongs to another task'; END IF;
   IF TG_OP='INSERT' THEN
     IF t.state<>'running' OR a.finished_at IS NOT NULL OR a.lease_expires_at<=clock_timestamp() THEN
        RAISE EXCEPTION 'stale execution lease'; END IF;
     SELECT (SELECT count(*) FROM collection_calls c JOIN collection_jobs job_lookup ON job_lookup.id=c.job_id WHERE job_lookup.task_id=t.id)
          + (SELECT count(*) FROM ai_executions WHERE task_id=t.id) INTO n;
     IF n>=t.max_external_calls THEN RAISE EXCEPTION 'BUDGET_EXHAUSTED'; END IF;
     IF TG_TABLE_NAME='collection_calls' THEN
       NEW.reserved_at:=clock_timestamp();
       IF NEW.outcome IS NOT NULL OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'call must reserve before completion'; END IF;
       IF NEW.sequence_no<>(SELECT count(*)+1 FROM collection_calls WHERE job_id=j.id) THEN RAISE EXCEPTION 'call sequence conflict'; END IF;
       IF (SELECT count(*) FROM collection_calls WHERE job_id=j.id)>=j.max_requests THEN
          RAISE EXCEPTION 'job budget exhausted'; END IF;
       IF j.plan_id IS NOT NULL AND t.execution_authorized_by IS DISTINCT FROM
          (SELECT authorized_by FROM collection_plans WHERE id=j.plan_id) THEN
          RAISE EXCEPTION 'plan authorizer changed'; END IF;
     ELSE
       NEW.started_at:=clock_timestamp();
       IF NEW.result_state IS NOT NULL OR NEW.finished_at IS NOT NULL THEN RAISE EXCEPTION 'AI must reserve before completion'; END IF;
       IF NEW.invocation_no<>(SELECT count(*)+1 FROM ai_executions WHERE attempt_id=a.id) THEN RAISE EXCEPTION 'AI invocation sequence conflict'; END IF;
     END IF;
   ELSIF (to_jsonb(OLD)->>'finished_at') IS NOT NULL OR
         (to_jsonb(OLD)->>'completed_at') IS NOT NULL THEN
     -- Explicit billing fields can be attached later; never rewrite a response.
     IF TG_TABLE_NAME='ai_executions' OR
       (to_jsonb(NEW)-ARRAY['billed_amount','currency','billing_reference']) IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['billed_amount','currency','billing_reference']) THEN
       RAISE EXCEPTION 'completed execution immutable'; END IF;
   END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cip_identity_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE p predictions; d prediction_drafts; expected jsonb; next_no bigint; prev review_decisions;
        req review_requests; ai review_decisions; head uuid;
BEGIN
 IF TG_TABLE_NAME='organizations' AND TG_OP='UPDATE' THEN
   IF NEW.authz_version IS DISTINCT FROM OLD.authz_version AND pg_trigger_depth()<2 THEN
     RAISE EXCEPTION 'authz_version only advanced by authorization changes'; END IF;
 ELSIF TG_TABLE_NAME='grants' AND TG_OP='UPDATE' THEN
   IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
     RAISE EXCEPTION 'revocation cannot be undone'; END IF;
 ELSIF TG_TABLE_NAME='raw_asset_events' THEN
   PERFORM 1 FROM raw_assets WHERE id=NEW.raw_asset_id FOR UPDATE;
   SELECT COALESCE(max(event_no),0)+1 INTO next_no FROM raw_asset_events WHERE raw_asset_id=NEW.raw_asset_id;
   IF NEW.event_no<>next_no THEN RAISE EXCEPTION 'event sequence conflict'; END IF;
 ELSIF TG_TABLE_NAME='knowledge_publications' THEN
   PERFORM 1 FROM knowledge_items WHERE id=NEW.knowledge_id FOR UPDATE;
   PERFORM 1 FROM review_requests WHERE id=NEW.review_request_id FOR UPDATE;
   IF NEW.revision_id IS DISTINCT FROM (SELECT current_revision_id FROM knowledge_items WHERE id=NEW.knowledge_id) THEN
      RAISE EXCEPTION 'publication must match current candidate'; END IF;
 ELSIF TG_TABLE_NAME='predictions' AND TG_OP='INSERT' THEN
   SELECT * INTO d FROM prediction_drafts WHERE id=NEW.draft_id FOR UPDATE;
   IF d.lock_version IS DISTINCT FROM NEW.draft_lock_version OR d.reliability<>'estimable' THEN
     RAISE EXCEPTION 'VERSION_CONFLICT or insufficient evidence'; END IF;
   expected:=to_jsonb(d)-ARRAY['id','org_id','created_at','updated_at','lock_version','reliability'];
   IF expected IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['id','org_id','created_at','sealed_at',
       'draft_id','draft_lock_version','frozen_at','freeze_transaction','frozen_by','content_sha256']) THEN
     RAISE EXCEPTION 'frozen prediction must exactly copy draft'; END IF;
   NEW.frozen_at:=clock_timestamp();
   NEW.freeze_transaction:=pg_current_xact_id();
 ELSIF TG_TABLE_NAME='prediction_events' THEN
   SELECT * INTO p FROM predictions WHERE id=NEW.prediction_id;
   -- A second transaction is proved using MVCC visibility from a fresh snapshot: the
   -- dedicated confirmation function below uses a separate connection at service level.
   IF p.sealed_at IS NULL OR pg_xact_status(p.freeze_transaction) IS DISTINCT FROM 'committed' THEN
     RAISE EXCEPTION 'prediction first transaction must commit before confirmation'; END IF;
   IF NEW.event_kind='freeze_confirmed' AND NEW.actor_member_id<>p.frozen_by THEN
     RAISE EXCEPTION 'only original freezer confirms'; END IF;
   NEW.occurred_at:=clock_timestamp();
 ELSIF TG_TABLE_NAME IN ('review_decisions','review_heads') THEN
   SELECT * INTO req FROM review_requests WHERE id=NEW.request_id FOR UPDATE;
   IF EXISTS(SELECT 1 FROM knowledge_publications WHERE review_request_id=req.id) OR
      EXISTS(SELECT 1 FROM standards s WHERE s.active_revision_id=req.standard_revision_id) THEN
      RAISE EXCEPTION 'published review basis is closed'; END IF;
   IF TG_TABLE_NAME='review_decisions' THEN
     IF NEW.input_sha256<>req.input_sha256 THEN RAISE EXCEPTION 'review input hash mismatch'; END IF;
     SELECT decision_id INTO head FROM review_heads WHERE request_id=req.id AND reviewer_kind=NEW.reviewer_kind;
     IF NEW.supersedes_decision_id IS DISTINCT FROM head THEN RAISE EXCEPTION 'REVIEW_STALE supersedes'; END IF;
     IF NEW.reviewer_kind='human' AND req.purpose IN ('knowledge_release','report_review') THEN
       SELECT reviewed.* INTO ai FROM review_heads h JOIN review_decisions reviewed ON reviewed.id=h.decision_id
         WHERE h.request_id=req.id AND h.reviewer_kind='ai';
       IF NEW.reviewed_ai_decision_id IS DISTINCT FROM ai.id THEN RAISE EXCEPTION 'REVIEW_STALE AI binding'; END IF;
       IF NEW.verdict='approved' AND (ai.id IS NULL OR ai.verdict<>'approved') THEN
         RAISE EXCEPTION 'approved AI required'; END IF;
     END IF;
   ELSE
     SELECT * INTO prev FROM review_decisions WHERE id=NEW.decision_id;
     IF (TG_OP='UPDATE' AND prev.supersedes_decision_id IS DISTINCT FROM OLD.decision_id) OR
        (TG_OP='INSERT' AND prev.supersedes_decision_id IS NOT NULL) THEN
        RAISE EXCEPTION 'head must advance through current decision'; END IF;
   END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cip_authz_changed() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE oid uuid;
BEGIN
 oid:=(CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END->>'org_id')::uuid;
 UPDATE organizations SET authz_version=authz_version+1,lock_version=lock_version+1 WHERE id=oid;
 RETURN NULL;
END $$;
"""

# Deferred validator queries final state. Scope all checks by tenant and use only
# persisted relations; JSON IDs never substitute for FK checks.
VALIDATOR = r"""
CREATE FUNCTION cip_validate() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE o uuid; row_data jsonb; stamp timestamptz; standard_row record; seal_table text; bad boolean;
BEGIN
 row_data:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 o:=(row_data->>'org_id')::uuid;
 IF o IS NULL THEN RETURN NULL; END IF;
 FOR seal_table IN SELECT unnest(ARRAY[__SEALED__]) LOOP
   EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I WHERE org_id=$1 AND sealed_at IS NULL)',seal_table) INTO bad USING o;
   IF bad THEN RAISE EXCEPTION 'unsealed % cannot commit',seal_table; END IF;
 END LOOP;
 IF TG_TABLE_NAME IN (__SEALED__) THEN
   EXECUTE format('SELECT sealed_at FROM %I WHERE id=$1',TG_TABLE_NAME) INTO stamp USING (row_data->>'id')::uuid;
   IF stamp IS NULL THEN RAISE EXCEPTION 'unsealed % cannot commit',TG_TABLE_NAME; END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM artifacts WHERE org_id=o AND current_version_id IS NULL) OR
    EXISTS(SELECT 1 FROM knowledge_items WHERE org_id=o AND current_revision_id IS NULL) THEN
    RAISE EXCEPTION 'current pointer required at commit'; END IF;
 IF EXISTS(SELECT 1 FROM artifact_versions v WHERE v.org_id=o AND v.body_text IS NULL AND v.file_id IS NULL
   AND NOT EXISTS(SELECT 1 FROM artifact_version_sources s WHERE s.artifact_version_id=v.id)) THEN
    RAISE EXCEPTION 'artifact requires actual carrier or source'; END IF;
 IF EXISTS(SELECT 1 FROM input_sets s WHERE s.org_id=o AND NOT EXISTS(
   SELECT 1 FROM input_set_items i WHERE i.input_set_id=s.id AND i.role='primary')) THEN
    RAISE EXCEPTION 'input set requires primary'; END IF;
 IF EXISTS(SELECT 1 FROM knowledge_revisions k WHERE k.org_id=o AND NOT EXISTS(
   SELECT 1 FROM knowledge_businesses b WHERE b.revision_id=k.id)) THEN
    RAISE EXCEPTION 'knowledge requires business'; END IF;
 IF EXISTS(SELECT 1 FROM input_sets s JOIN works w ON w.id=s.work_id WHERE s.org_id=o AND s.business_code<>w.business_code) OR
    EXISTS(SELECT 1 FROM content_units u JOIN works w ON w.id=u.work_id WHERE u.org_id=o AND u.episode_no>w.total_episode_count) THEN
    RAISE EXCEPTION 'work business or episode boundary mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM input_set_items i JOIN input_sets s ON s.id=i.input_set_id
  JOIN artifact_versions v ON v.id=i.artifact_version_id WHERE s.org_id=o AND i.role='primary' AND
  ((s.scope='artifact' AND s.artifact_id<>v.artifact_id) OR (s.scope='unit' AND NOT EXISTS(
   SELECT 1 FROM artifact_version_units u WHERE u.artifact_version_id=v.id AND u.unit_id=s.unit_id)))) THEN
    RAISE EXCEPTION 'primary material outside input scope'; END IF;
 -- Immutable file bytes are usable only after accepted validation.
 IF EXISTS(SELECT 1 FROM raw_assets a JOIN file_objects f ON f.id=a.file_id WHERE a.org_id=o AND f.validation_state<>'accepted') OR
    EXISTS(SELECT 1 FROM artifact_versions a JOIN file_objects f ON f.id=a.file_id WHERE a.org_id=o AND f.validation_state<>'accepted') OR
    EXISTS(SELECT 1 FROM ai_executions a JOIN file_objects f ON f.id IN (a.input_manifest_file_id,a.output_file_id)
           WHERE a.org_id=o AND f.validation_state<>'accepted') THEN
    RAISE EXCEPTION 'file must be accepted before use'; END IF;
 IF EXISTS(SELECT 1 FROM external_contents c JOIN external_accounts a ON a.id=c.account_id WHERE c.org_id=o AND c.platform_code<>a.platform_code) OR
    EXISTS(SELECT 1 FROM sources s JOIN external_accounts a ON a.id=s.account_id WHERE s.org_id=o AND s.platform_code<>a.platform_code) OR
    EXISTS(SELECT 1 FROM sources s JOIN external_contents c ON c.id=s.content_id WHERE s.org_id=o AND s.platform_code<>c.platform_code) THEN
    RAISE EXCEPTION 'platform mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM collection_jobs j JOIN sources s ON s.id=j.source_id JOIN tasks t ON t.id=j.task_id
  LEFT JOIN collection_plans p ON p.id=j.plan_id WHERE j.org_id=o AND (j.business_code<>s.business_code OR
   t.source_id IS DISTINCT FROM s.id OR t.business_code IS DISTINCT FROM j.business_code OR
   j.business_date<>(COALESCE(j.scheduled_for,t.created_at) AT TIME ZONE 'Asia/Shanghai')::date OR
   (j.plan_id IS NOT NULL AND (p.source_id<>j.source_id OR p.connection_id<>j.connection_id OR
    p.capability_code<>j.capability_code OR p.connector_version<>j.connector_version)))) THEN
    RAISE EXCEPTION 'job route or business date mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM raw_assets a JOIN collection_calls c ON c.id=a.collection_call_id
  WHERE a.org_id=o AND a.collection_job_id<>c.job_id) THEN RAISE EXCEPTION 'raw call job mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM intelligence_snapshots s JOIN collection_jobs j ON j.id=s.job_id WHERE s.org_id=o AND
    (s.source_id<>j.source_id OR s.business_code<>j.business_code OR s.business_date<>j.business_date OR
     s.entry_count<>(SELECT count(*) FROM snapshot_entries e WHERE e.snapshot_id=s.id) OR
     NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success'))) THEN
    RAISE EXCEPTION 'snapshot provenance or count mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id
  LEFT JOIN account_observations a ON a.id=e.account_observation_id
  LEFT JOIN content_observations c ON c.id=e.content_observation_id
  JOIN raw_assets r ON r.id=COALESCE(a.raw_asset_id,c.raw_asset_id) WHERE s.org_id=o AND
  (r.collection_job_id IS DISTINCT FROM s.job_id OR (r.captured_at AT TIME ZONE 'Asia/Shanghai')::date<>s.business_date)) THEN
    RAISE EXCEPTION 'DATE_WINDOW_MISMATCH or mixed job'; END IF;
 IF EXISTS(SELECT 1 FROM feedback_snapshots f WHERE f.org_id=o AND
    (f.sample_count<>(SELECT count(*) FROM feedback_comments c WHERE c.feedback_id=f.id) OR
     f.classified_count<>(SELECT count(DISTINCT e.comment_id) FROM feedback_claim_evidence e
      JOIN feedback_claims c ON c.id=e.claim_id WHERE e.feedback_id=f.id AND c.kind='emotion'))) OR
    EXISTS(SELECT 1 FROM feedback_claims c WHERE c.org_id=o AND c.support_count<>(
     SELECT count(*) FROM feedback_claim_evidence e WHERE e.claim_id=c.id)) THEN
    RAISE EXCEPTION 'feedback frozen count mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM feedback_comments fc JOIN feedback_snapshots f ON f.id=fc.feedback_id
  JOIN comment_evidence c ON c.id=fc.comment_id WHERE f.org_id=o AND NOT EXISTS(
    SELECT 1 FROM snapshot_entries e JOIN content_observations v ON v.id=e.content_observation_id
    WHERE e.snapshot_id=f.snapshot_id AND v.content_id=c.content_id)) THEN
    RAISE EXCEPTION 'feedback comment outside snapshot'; END IF;
 IF EXISTS(SELECT 1 FROM research_submissions s LEFT JOIN snapshot_entries e ON e.id=s.snapshot_entry_id
  LEFT JOIN feedback_snapshots f ON f.id=s.feedback_id WHERE s.org_id=o AND
   ((s.feedback_id IS NOT NULL AND f.snapshot_id<>e.snapshot_id) OR
    (s.origin='intelligence' AND NOT EXISTS(SELECT 1 FROM preliminary_assessments p WHERE p.submission_id=s.id)))) THEN
    RAISE EXCEPTION 'intake requires initial assessment and matching feedback'; END IF;
 IF EXISTS(SELECT 1 FROM preliminary_assessments p JOIN research_submissions s ON s.id=p.submission_id
  JOIN works w ON w.id=s.work_id WHERE p.org_id=o AND (p.confirmed_business_code<>w.business_code OR
   (s.origin='intelligence' AND (p.quality_grade IS NULL OR jsonb_array_length(p.confirmed_genre_tags)=0 OR
    (jsonb_array_length(p.learning_tags)=0 AND COALESCE(btrim(p.additional_learning),'')=''))))) THEN
    RAISE EXCEPTION 'intake assessment incomplete or wrong business'; END IF;
 -- Task state and output closure, including the empty-output success case.
 IF EXISTS(SELECT 1 FROM tasks t WHERE t.org_id=o AND (t.inputs_sealed_at IS NULL OR
   (t.state='succeeded' AND (t.outputs_sealed_at IS NULL OR t.inputs_frozen_at IS NULL)) OR
   (t.state<>'succeeded' AND t.outputs_sealed_at IS NOT NULL) OR
   (t.state IN ('failed','cancelled') AND EXISTS(SELECT 1 FROM task_outputs x WHERE x.task_id=t.id)) OR
   (t.state IN ('running','cancel_requested') AND t.inputs_frozen_at IS NULL))) THEN
    RAISE EXCEPTION 'task closure or frozen state invalid'; END IF;
 IF EXISTS(SELECT 1 FROM tasks t WHERE t.org_id=o AND t.state='running' AND NOT EXISTS(
   SELECT 1 FROM task_attempts a WHERE a.task_id=t.id AND a.finished_at IS NULL)) OR
    EXISTS(SELECT 1 FROM task_attempts a JOIN tasks t ON t.id=a.task_id WHERE a.org_id=o AND a.finished_at IS NULL
      AND t.state NOT IN ('running','cancel_requested')) THEN
    RAISE EXCEPTION 'task active attempt mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM tasks t WHERE t.org_id=o AND t.state='succeeded' AND NOT EXISTS(
  SELECT 1 FROM task_attempts a WHERE a.task_id=t.id AND a.outcome='succeeded'
   AND a.attempt_no=(SELECT max(attempt_no) FROM task_attempts WHERE task_id=t.id)
   AND a.finished_at<=a.lease_expires_at)) THEN RAISE EXCEPTION 'stale result or lease lost'; END IF;
 IF EXISTS(SELECT 1 FROM tasks t WHERE t.org_id=o AND t.state='cancelled' AND (
   EXISTS(SELECT 1 FROM collection_calls c JOIN collection_jobs job_lookup ON job_lookup.id=c.job_id WHERE job_lookup.task_id=t.id AND c.outcome IS NULL) OR
   EXISTS(SELECT 1 FROM ai_executions e WHERE e.task_id=t.id AND e.result_state IS NULL))) THEN
    RAISE EXCEPTION 'external result unknown; cancellation unconfirmed'; END IF;
 IF EXISTS(SELECT 1 FROM analysis_runs r JOIN tasks t ON t.id=r.task_id WHERE r.org_id=o AND
  (r.state<>t.state OR r.started_at IS DISTINCT FROM t.started_at OR r.finished_at IS DISTINCT FROM t.finished_at OR
   r.safe_error_code IS DISTINCT FROM t.safe_error_code)) THEN RAISE EXCEPTION 'run must mirror task'; END IF;
 IF EXISTS(SELECT 1 FROM ai_executions e JOIN task_attempts a ON a.id=e.attempt_id WHERE e.org_id=o AND e.task_id<>a.task_id) OR
    EXISTS(SELECT 1 FROM collection_calls c JOIN task_attempts a ON a.id=c.attempt_id JOIN collection_jobs j ON j.id=c.job_id
      WHERE c.org_id=o AND a.task_id<>j.task_id) THEN RAISE EXCEPTION 'attempt task mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM analysis_reports p JOIN analysis_runs r ON r.id=p.analysis_run_id
  JOIN ai_executions e ON e.id=p.ai_execution_id WHERE p.org_id=o AND
  (p.input_set_id<>r.input_set_id OR r.task_id<>e.task_id OR r.ai_config_revision_id<>e.config_revision_id OR
   e.result_state IS DISTINCT FROM p.result_state)) OR
    EXISTS(SELECT 1 FROM quality_evaluations q JOIN ai_executions e ON e.id=q.ai_execution_id
     LEFT JOIN analysis_reports p ON p.id=q.report_id WHERE q.org_id=o AND
     (q.task_id<>e.task_id OR e.result_state IS DISTINCT FROM q.result_state OR
      (q.report_id IS NOT NULL AND p.input_set_id<>q.input_set_id))) OR
    EXISTS(SELECT 1 FROM feedback_snapshots f JOIN ai_executions e ON e.id=f.ai_execution_id WHERE f.org_id=o AND f.task_id<>e.task_id) THEN
    RAISE EXCEPTION 'result execution or input mismatch'; END IF;
 -- Every model/config/input reference must be part of the Task's sealed manifest.
 IF EXISTS(SELECT 1 FROM ai_executions e WHERE e.org_id=o AND NOT EXISTS(
   SELECT 1 FROM task_inputs i WHERE i.task_id=e.task_id AND i.ai_config_revision_id=e.config_revision_id)) OR
    EXISTS(SELECT 1 FROM analysis_runs r WHERE r.org_id=o AND NOT EXISTS(
     SELECT 1 FROM task_inputs i WHERE i.task_id=r.task_id AND i.input_set_id=r.input_set_id)) OR
    EXISTS(SELECT 1 FROM quality_evaluations q WHERE q.org_id=o AND NOT EXISTS(
     SELECT 1 FROM task_inputs i WHERE i.task_id=q.task_id AND i.input_set_id=q.input_set_id)) OR
    EXISTS(SELECT 1 FROM feedback_snapshots f WHERE f.org_id=o AND NOT EXISTS(
     SELECT 1 FROM task_inputs i WHERE i.task_id=f.task_id AND i.snapshot_id=f.snapshot_id)) THEN
    RAISE EXCEPTION 'execution input outside task manifest'; END IF;
 -- Standard type checks are separate from mutable active pointers.
 IF EXISTS(SELECT 1 FROM ai_config_revisions c JOIN standard_revisions r ON r.id=c.prompt_revision_id
  JOIN standards s ON s.id=r.standard_id WHERE c.org_id=o AND s.kind<>'prompt') OR
    EXISTS(SELECT 1 FROM analysis_runs a JOIN standard_revisions r ON r.id=a.template_revision_id
     JOIN standards s ON s.id=r.standard_id WHERE a.org_id=o AND s.kind<>'analysis_template') THEN
    RAISE EXCEPTION 'standard kind mismatch'; END IF;
 FOR standard_row IN SELECT rubric_revision_id AS rid FROM analysis_runs WHERE org_id=o
    UNION ALL SELECT rubric_revision_id FROM quality_evaluations WHERE org_id=o
    UNION ALL SELECT rubric_revision_id FROM prediction_drafts WHERE org_id=o
    UNION ALL SELECT rubric_revision_id FROM predictions WHERE org_id=o LOOP
   IF standard_row.rid IS NOT NULL AND NOT EXISTS(SELECT 1 FROM standard_revisions v JOIN standards s ON s.id=v.standard_id
      WHERE v.id=standard_row.rid AND s.kind='rubric') THEN RAISE EXCEPTION 'rubric kind mismatch'; END IF;
 END LOOP;
 FOR standard_row IN SELECT prompt_revision_id AS rid FROM prediction_drafts WHERE org_id=o
    UNION ALL SELECT prompt_revision_id FROM predictions WHERE org_id=o LOOP
   IF standard_row.rid IS NOT NULL AND NOT EXISTS(SELECT 1 FROM standard_revisions v JOIN standards s ON s.id=v.standard_id
      WHERE v.id=standard_row.rid AND s.kind='prompt') THEN RAISE EXCEPTION 'prompt kind mismatch'; END IF;
 END LOOP;
 -- Formal index binds the exact publication, never a candidate revision.
 IF EXISTS(SELECT 1 FROM search_documents d JOIN knowledge_publications p ON p.id=d.publication_id
  WHERE d.org_id=o AND d.revision_id<>p.revision_id) OR
    EXISTS(SELECT 1 FROM embeddings e JOIN search_documents d ON d.id=e.search_document_id
      WHERE e.org_id=o AND e.end_offset>char_length(d.document_text)) THEN RAISE EXCEPTION 'formal index mismatch'; END IF;
 RETURN NULL;
END $$;
"""


def build():
    sealed_list = ",".join(repr(n) for n in SEALED)
    parts = [
        HEADER.replace("__SEALED__", sealed_list),
        VALIDATOR.replace("__SEALED__", sealed_list),
    ]
    for name, obj in metadata.tables.items():
        if name in ("business_lines", "platforms"):
            allowed = ""
        else:
            allowed = ",".join(MUTABLE.get(name, ["sealed_at"] if name in SEALED else []))
        mode = "sealed" if name in SEALED else "ordinary"
        parts.append(
            f"CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON {name} "
            f"FOR EACH ROW EXECUTE FUNCTION cip_immutable('{allowed}','{mode}');"
        )
        if name in SEALED:
            parts.append(
                f"CREATE TRIGGER a_new_seal BEFORE INSERT ON {name} "
                "FOR EACH ROW EXECUTE FUNCTION cip_new_seal();"
            )
        if name in CHILDREN:
            parent, key, col = CHILDREN[name]
            parts.append(
                f"CREATE TRIGGER a_parent BEFORE INSERT OR UPDATE OR DELETE ON {name} "
                f"FOR EACH ROW EXECUTE FUNCTION cip_parent_open('{parent}','{key}','{col}');"
            )
        if "org_id" in obj.c:
            parts.append(
                f"CREATE CONSTRAINT TRIGGER zz_integrity AFTER INSERT OR UPDATE OR DELETE ON {name} "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_validate();"
            )
    parts.append(
        "CREATE TRIGGER b_task BEFORE INSERT OR UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION cip_task_guard();"
    )
    for name in ["task_attempts", "collection_calls", "ai_executions"]:
        parts.append(
            f"CREATE TRIGGER b_runtime BEFORE INSERT OR UPDATE ON {name} FOR EACH ROW EXECUTE FUNCTION cip_runtime_guard();"
        )
    for name in [
        "organizations",
        "grants",
        "raw_asset_events",
        "predictions",
        "prediction_events",
        "review_decisions",
        "review_heads",
        "knowledge_publications",
    ]:
        parts.append(
            f"CREATE TRIGGER b_identity BEFORE INSERT OR UPDATE ON {name} FOR EACH ROW EXECUTE FUNCTION cip_identity_guard();"
        )
    for name in ["grants", "members", "role_actions", "raw_asset_events"]:
        parts.append(
            f"CREATE TRIGGER z_authz AFTER INSERT OR UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION cip_authz_changed();"
        )
    return "\n\n".join(parts)
