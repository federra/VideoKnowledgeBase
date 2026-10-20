"""Frozen S04 relational guard source."""

SQL = r"""
CREATE FUNCTION cip_graph_edges(organization uuid)
RETURNS TABLE(child text,parent text) LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 SELECT 'r:'||id,'r:'||parent_raw_asset_id FROM raw_assets WHERE org_id=organization AND parent_raw_asset_id IS NOT NULL
 UNION ALL SELECT 'r:'||id,'v:'||parent_artifact_version_id FROM raw_assets WHERE org_id=organization AND parent_artifact_version_id IS NOT NULL
 UNION ALL SELECT 'v:'||artifact_version_id,'r:'||raw_asset_id FROM artifact_version_sources WHERE org_id=organization
 UNION ALL SELECT 'v:'||from_version_id,'v:'||to_version_id FROM artifact_lineage WHERE org_id=organization
$$;

CREATE FUNCTION cip_input_contains(organization uuid,input_id uuid,evidence uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 WITH RECURSIVE reachable(node,path) AS (
  SELECT 'v:'||artifact_version_id, ARRAY['v:'||artifact_version_id] FROM input_set_items WHERE org_id=organization AND input_set_id=input_id
  UNION ALL SELECT g.parent,r.path||g.parent FROM reachable r JOIN cip_graph_edges(organization) g ON g.child=r.node
     WHERE NOT g.parent=ANY(r.path) AND cardinality(r.path)<=32
 ) SELECT EXISTS(SELECT 1 FROM reachable r JOIN evidence_refs e ON e.org_id=organization AND e.id=evidence
    WHERE r.node=COALESCE('r:'||e.raw_asset_id,'v:'||e.artifact_version_id))
$$;

CREATE FUNCTION cip_relationships() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE o uuid; body jsonb; bad boolean; aid uuid; request review_requests; decision review_decisions;
BEGIN
 body:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 o:=(body->>'org_id')::uuid;
 -- Tenant lock serializes cross-table edge insertion, including cycles formed by two writers.
 -- It is taken by the immediate write guard, before modifications are visible.
 WITH RECURSIVE walk(root,node,path,cycle,depth) AS (
   SELECT child,parent,ARRAY[child,parent],child=parent,1 FROM cip_graph_edges(o)
   UNION ALL SELECT w.root,g.parent,w.path||g.parent,g.parent=ANY(w.path),w.depth+1
     FROM walk w JOIN cip_graph_edges(o) g ON g.child=w.node WHERE NOT w.cycle AND w.depth<=32
 ) SELECT EXISTS(SELECT 1 FROM walk WHERE cycle OR depth>32) INTO bad;
 IF bad THEN RAISE EXCEPTION 'processing graph cycle or depth exceeds 32'; END IF;
 IF EXISTS(SELECT 1 FROM raw_assets a JOIN tasks t ON t.id=a.processing_task_id WHERE a.org_id=o AND a.origin='processing' AND
    (t.inputs_frozen_at IS NULL OR NOT EXISTS(SELECT 1 FROM task_inputs i WHERE i.task_id=t.id AND
       (i.raw_asset_id=a.parent_raw_asset_id OR i.artifact_version_id=a.parent_artifact_version_id OR
        (i.input_set_id IS NOT NULL AND EXISTS(SELECT 1 FROM input_set_items m WHERE m.input_set_id=i.input_set_id
             AND m.artifact_version_id=a.parent_artifact_version_id)))))) THEN
    RAISE EXCEPTION 'processing parent outside frozen task inputs'; END IF;
 IF EXISTS(SELECT 1 FROM artifact_lineage l JOIN artifact_versions v1 ON v1.id=l.from_version_id
    JOIN works w1 ON w1.id=v1.work_id JOIN artifact_versions v2 ON v2.id=l.to_version_id
    JOIN works w2 ON w2.id=v2.work_id WHERE l.org_id=o AND w1.business_code<>w2.business_code) THEN
    RAISE EXCEPTION 'lineage business mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM report_evidence x JOIN analysis_reports r ON r.id=x.report_id WHERE x.org_id=o AND
    NOT cip_input_contains(o,r.input_set_id,x.evidence_id)) OR
    EXISTS(SELECT 1 FROM evaluation_evidence x JOIN quality_evaluations q ON q.id=x.evaluation_id WHERE x.org_id=o AND
    NOT cip_input_contains(o,q.input_set_id,x.evidence_id)) OR
    EXISTS(SELECT 1 FROM prediction_evidence x JOIN predictions p ON p.id=x.prediction_id WHERE x.org_id=o AND
    NOT cip_input_contains(o,p.input_set_id,x.evidence_id)) THEN
    RAISE EXCEPTION 'evidence outside frozen input graph'; END IF;
 -- Text locator bounds can be verified now. Page/time bounds require accepted parsed
 -- content; raw file presence alone never proves page count or video duration.
 IF EXISTS(SELECT 1 FROM evidence_refs e LEFT JOIN raw_assets a ON a.id=e.raw_asset_id
    LEFT JOIN artifact_versions v ON v.id=e.artifact_version_id WHERE e.org_id=o AND
     ((e.locator_kind='paragraph' AND (COALESCE(a.body_text,v.body_text) IS NULL OR
       e.paragraph_no>cardinality(string_to_array(COALESCE(a.body_text,v.body_text),E'\n')))) OR
      e.locator_kind IN ('page','time'))) THEN
    RAISE EXCEPTION 'evidence locator lacks verified source bounds'; END IF;
 -- Review target hash must equal the frozen target, including standard/evaluation.
 IF EXISTS(SELECT 1 FROM review_requests r
    LEFT JOIN knowledge_revisions k ON k.id=r.knowledge_revision_id
    LEFT JOIN analysis_reports p ON p.id=r.report_id
    LEFT JOIN standard_revisions s ON s.id=r.standard_revision_id
    LEFT JOIN quality_evaluations q ON q.id=r.evaluation_id
    WHERE r.org_id=o AND
      r.input_sha256 IS DISTINCT FROM COALESCE(k.content_sha256,p.content_sha256,s.content_sha256,q.content_sha256)) THEN
    RAISE EXCEPTION 'review target digest mismatch'; END IF;
 -- Every appended decision must be installed as head before commit, or be in the
 -- supersedes chain of the installed head (multiple same-transaction decisions).
 IF EXISTS(SELECT 1 FROM review_decisions d WHERE d.org_id=o AND NOT EXISTS(
   WITH RECURSIVE chain(id,previous) AS (
    SELECT h.decision_id,x.supersedes_decision_id FROM review_heads h JOIN review_decisions x ON x.id=h.decision_id
      WHERE h.request_id=d.request_id AND h.reviewer_kind=d.reviewer_kind
    UNION ALL SELECT x.id,x.supersedes_decision_id FROM chain c JOIN review_decisions x ON x.id=c.previous
   ) SELECT 1 FROM chain WHERE id=d.id)) THEN RAISE EXCEPTION 'review decision has no effective head chain'; END IF;
 IF EXISTS(SELECT 1 FROM review_decisions d JOIN ai_executions e ON e.id=d.ai_execution_id
   JOIN ai_config_revisions c ON c.id=e.config_revision_id WHERE d.org_id=o AND d.reviewer_kind='ai' AND
    (e.result_state IS DISTINCT FROM 'completed' OR NOT EXISTS(
      SELECT 1 FROM task_inputs i WHERE i.task_id=e.task_id AND i.review_request_id=d.request_id))) THEN
    RAISE EXCEPTION 'AI review execution does not review this request'; END IF;
 IF EXISTS(SELECT 1 FROM knowledge_publications p JOIN knowledge_items k ON k.id=p.knowledge_id
   JOIN knowledge_revisions v ON v.id=p.revision_id JOIN review_requests r ON r.id=p.review_request_id
   JOIN review_decisions a ON a.id=p.ai_decision_id JOIN review_decisions h ON h.id=p.human_decision_id
   WHERE p.org_id=o AND (r.purpose<>'knowledge_release' OR r.knowledge_revision_id<>v.id OR
     a.reviewer_kind<>'ai' OR h.reviewer_kind<>'human' OR a.verdict<>'approved' OR h.verdict<>'approved' OR
     h.reviewed_ai_decision_id IS DISTINCT FROM a.id OR a.input_sha256<>v.content_sha256 OR h.input_sha256<>v.content_sha256 OR
     NOT EXISTS(SELECT 1 FROM review_heads x WHERE x.request_id=r.id AND x.reviewer_kind='ai' AND x.decision_id=a.id) OR
     NOT EXISTS(SELECT 1 FROM review_heads x WHERE x.request_id=r.id AND x.reviewer_kind='human' AND x.decision_id=h.id))) THEN
    RAISE EXCEPTION 'knowledge publication requires current approved double review'; END IF;
 -- Published history may differ from current candidate; only switching the pointer
 -- must approve the current revision, enforced by the immediate pointer guard below.
 IF EXISTS(SELECT 1 FROM standards s JOIN standard_revisions v ON v.id=s.active_revision_id WHERE s.org_id=o AND
    (v.origin_kind='learning_candidate' OR NOT EXISTS(SELECT 1 FROM review_requests r
      JOIN review_heads h ON h.request_id=r.id AND h.reviewer_kind='human'
      JOIN review_decisions d ON d.id=h.decision_id WHERE r.standard_revision_id=v.id AND
       r.purpose='standard_approval' AND d.verdict='approved' AND d.input_sha256=v.content_sha256))) THEN
    RAISE EXCEPTION 'STANDARD_NOT_APPROVED'; END IF;
 IF EXISTS(SELECT 1 FROM predictions p LEFT JOIN external_accounts a ON a.id=p.account_id
   LEFT JOIN ai_executions e ON e.id=p.ai_execution_id LEFT JOIN ai_config_revisions c ON c.id=e.config_revision_id
   WHERE p.org_id=o AND ((p.account_id IS NOT NULL AND p.platform_code<>a.platform_code) OR
     (p.author_kind='ai' AND (e.result_state IS DISTINCT FROM 'completed' OR
       p.prompt_revision_id IS DISTINCT FROM c.prompt_revision_id OR NOT EXISTS(
        SELECT 1 FROM task_inputs i WHERE i.task_id=e.task_id AND i.input_set_id=p.input_set_id))))) THEN
    RAISE EXCEPTION 'prediction platform or AI input mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM task_outputs x LEFT JOIN ai_executions a ON a.id=x.ai_execution_id
      LEFT JOIN feedback_snapshots f ON f.id=x.feedback_id LEFT JOIN quality_evaluations q ON q.id=x.evaluation_id
      LEFT JOIN analysis_reports p ON p.id=x.report_id LEFT JOIN analysis_runs r ON r.id=p.analysis_run_id
      LEFT JOIN intelligence_snapshots snap ON snap.id=x.snapshot_id LEFT JOIN collection_jobs j ON j.id=snap.job_id
      LEFT JOIN raw_assets raw ON raw.id=x.raw_asset_id WHERE x.org_id=o AND
       ((a.id IS NOT NULL AND a.task_id<>x.task_id) OR (f.id IS NOT NULL AND f.task_id<>x.task_id) OR
        (q.id IS NOT NULL AND q.task_id<>x.task_id) OR (r.id IS NOT NULL AND r.task_id<>x.task_id) OR
        (j.id IS NOT NULL AND j.task_id<>x.task_id) OR (raw.processing_task_id IS NOT NULL AND raw.processing_task_id<>x.task_id) OR
        (raw.collection_job_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM collection_jobs z WHERE z.id=raw.collection_job_id AND z.task_id=x.task_id)))) THEN
       RAISE EXCEPTION 'output belongs to another task'; END IF;
 IF EXISTS(SELECT 1 FROM task_inputs i JOIN tasks t ON t.id=i.task_id JOIN input_sets s ON s.id=i.input_set_id
     WHERE t.org_id=o AND t.work_id IS DISTINCT FROM s.work_id) OR
    EXISTS(SELECT 1 FROM research_submissions s JOIN tasks t ON t.id=s.task_id WHERE s.org_id=o AND t.work_id IS DISTINCT FROM s.work_id) OR
    EXISTS(SELECT 1 FROM analysis_runs r JOIN tasks t ON t.id=r.task_id JOIN input_sets s ON s.id=r.input_set_id
     WHERE r.org_id=o AND t.work_id IS DISTINCT FROM s.work_id) OR
    EXISTS(SELECT 1 FROM quality_evaluations q JOIN tasks t ON t.id=q.task_id JOIN input_sets s ON s.id=q.input_set_id
     WHERE q.org_id=o AND t.work_id IS DISTINCT FROM s.work_id) THEN RAISE EXCEPTION 'task work root differs from primary input'; END IF;
 IF EXISTS(SELECT 1 FROM standards s JOIN standard_revisions v ON v.id=s.active_revision_id WHERE s.org_id=o
    AND s.kind='rubric' AND v.origin_kind<>'expert_baseline') THEN RAISE EXCEPTION 'B1 rubric requires expert baseline'; END IF;
 IF EXISTS(SELECT 1 FROM works w WHERE w.org_id=o AND w.report_generation<>
      COALESCE((SELECT max(r.report_generation) FROM analysis_runs r JOIN input_sets i ON i.id=r.input_set_id WHERE i.work_id=w.id),0)) OR
    EXISTS(SELECT 1 FROM analysis_runs r JOIN input_sets i ON i.id=r.input_set_id WHERE r.org_id=o
      GROUP BY i.work_id,r.report_generation HAVING count(*)>1) THEN
      RAISE EXCEPTION 'report generation must match unique run sequence'; END IF;
 IF EXISTS(SELECT 1 FROM tasks t WHERE t.org_id=o AND t.state='succeeded' AND (
    EXISTS(SELECT 1 FROM collection_calls c JOIN collection_jobs j ON j.id=c.job_id WHERE j.task_id=t.id AND c.outcome IS NULL) OR
    EXISTS(SELECT 1 FROM ai_executions e WHERE e.task_id=t.id AND e.result_state IS NULL))) THEN
    RAISE EXCEPTION 'external result unknown; cannot succeed'; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION cip_write_lock() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE o uuid; data jsonb;
BEGIN
 data:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 o:=(data->>'org_id')::uuid;
 -- Initial low-volume implementation uses a tenant transaction advisory mutex.
 -- No network I/O in this transaction. S05 services keep the documented finer lock order.
 PERFORM pg_advisory_xact_lock(hashtextextended('cip:b1:'||o::text,0));
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;

CREATE FUNCTION cip_pointer_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE v standard_revisions; p knowledge_publications; r analysis_runs;
BEGIN
 IF TG_OP='INSERT' THEN
   IF (to_jsonb(NEW)->>'active_revision_id') IS NOT NULL OR
      (to_jsonb(NEW)->>'latest_report_id') IS NOT NULL OR
      (to_jsonb(NEW)->>'published_publication_id') IS NOT NULL OR
      (to_jsonb(NEW)->>'current_version_id') IS NOT NULL OR
      (to_jsonb(NEW)->>'current_revision_id') IS NOT NULL OR
      COALESCE((to_jsonb(NEW)->>'report_generation')::bigint,0)<>0 THEN
      RAISE EXCEPTION 'initial pointer must be empty; advance through guarded update'; END IF;
   RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='standards' AND to_jsonb(NEW)->>'active_revision_id' IS DISTINCT FROM to_jsonb(OLD)->>'active_revision_id' THEN
   IF NEW.active_revision_id IS NULL THEN RAISE EXCEPTION 'standard deactivation requires B3'; END IF;
   SELECT * INTO v FROM standard_revisions WHERE id=NEW.active_revision_id;
   IF v.origin_kind='learning_candidate' OR
     (NEW.kind='rubric' AND (OLD.active_revision_id IS NOT NULL OR v.origin_kind<>'expert_baseline')) THEN
       RAISE EXCEPTION 'B1 rubric activation only first expert baseline'; END IF;
 ELSIF TG_TABLE_NAME='knowledge_items' AND to_jsonb(NEW)->>'published_publication_id' IS DISTINCT FROM to_jsonb(OLD)->>'published_publication_id' THEN
   SELECT * INTO p FROM knowledge_publications WHERE id=NEW.published_publication_id;
   IF p.id IS NULL OR p.revision_id IS DISTINCT FROM NEW.current_revision_id THEN
     RAISE EXCEPTION 'publication must match current candidate revision'; END IF;
 ELSIF TG_TABLE_NAME='works' THEN
   IF NEW.report_generation<OLD.report_generation OR NEW.report_generation>OLD.report_generation+1 THEN
     RAISE EXCEPTION 'report generation must advance once'; END IF;
   IF NEW.latest_report_id IS DISTINCT FROM OLD.latest_report_id THEN
    SELECT run_row.* INTO r FROM analysis_reports report_row JOIN analysis_runs run_row ON run_row.id=report_row.analysis_run_id WHERE report_row.id=NEW.latest_report_id;
    IF r.id IS NULL OR r.report_generation<>NEW.report_generation OR r.state<>'succeeded' OR EXISTS(
      SELECT 1 FROM input_set_items i JOIN artifact_versions version_row ON version_row.id=i.artifact_version_id
      JOIN artifacts artifact_row ON artifact_row.id=version_row.artifact_id WHERE i.input_set_id=r.input_set_id AND i.role='primary'
       AND artifact_row.current_version_id IS DISTINCT FROM version_row.id) THEN RAISE EXCEPTION 'stale report cannot become latest'; END IF;
   END IF;
 END IF;
 RETURN NEW;
END $$;


"""


def build(tables):
    parts = [SQL]
    for name, obj in tables.items():
        if "org_id" in obj.c:
            parts.append(
                f"CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION cip_write_lock();"
            )
            parts.append(
                f"CREATE CONSTRAINT TRIGGER zz_relationships AFTER INSERT OR UPDATE OR DELETE ON {name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_relationships();"
            )
    for name in ["standards", "works", "knowledge_items", "artifacts"]:
        parts.append(
            f"CREATE TRIGGER b_pointer BEFORE INSERT OR UPDATE ON {name} FOR EACH ROW EXECUTE FUNCTION cip_pointer_guard();"
        )
    return "\n".join(parts)
