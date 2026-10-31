-- Narrow the legacy count invariant only for v2's explicit unclassifiable emotion.
DO $$ DECLARE definition text; BEGIN
 definition:=pg_get_functiondef('cip_validate()'::regprocedure);
 definition:=replace(definition, 'WHERE e.feedback_id=f.id AND c.kind=''emotion''',
 'WHERE e.feedback_id=f.id AND c.kind=''emotion'' AND (c.details->>''sentiment'' IS DISTINCT FROM ''unclassifiable'' OR NOT EXISTS(SELECT 1 FROM tasks ft WHERE ft.id=f.task_id AND ft.org_id=f.org_id AND ft.kind=''audience.feedback'' AND ft.handler_version=''2''))');
 EXECUTE definition;
END $$;
CREATE FUNCTION cip_feedback_v2_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE r jsonb; organization uuid; ids uuid[]; identity uuid; t tasks%ROWTYPE; a raw_assets%ROWTYPE; d jsonb; s jsonb; f feedback_snapshots%ROWTYPE; e ai_executions%ROWTYPE;
BEGIN
 r:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 organization:=(r->>'org_id')::uuid;
 IF TG_TABLE_NAME='tasks' THEN ids:=ARRAY[(r->>'id')::uuid];
 ELSIF TG_TABLE_NAME IN ('task_inputs','task_outputs','task_attempts','ai_executions','feedback_snapshots') THEN ids:=ARRAY[(r->>'task_id')::uuid];
 ELSIF TG_TABLE_NAME IN ('feedback_comments','feedback_claims','feedback_claim_evidence') THEN
 SELECT ARRAY[task_id] INTO ids FROM feedback_snapshots WHERE org_id=organization AND id=(r->>'feedback_id')::uuid;
 ELSE SELECT array_agg(id) INTO ids FROM tasks WHERE org_id=organization AND kind='audience.feedback' AND handler_version='2' AND raw_asset_id=(r->>'id')::uuid;
 END IF;
 FOREACH identity IN ARRAY coalesce(ids,'{}'::uuid[]) LOOP
 SELECT * INTO t FROM tasks WHERE org_id=organization AND id=identity;
 IF t.kind IS DISTINCT FROM 'audience.feedback' OR t.handler_version IS DISTINCT FROM '2' THEN CONTINUE; END IF;
 SELECT * INTO a FROM raw_assets WHERE org_id=organization AND id=t.raw_asset_id;
 IF t.max_attempts<>1 OR t.max_external_calls<>1 OR a.origin IS DISTINCT FROM 'manual' OR a.submitted_by IS DISTINCT FROM t.requested_by OR a.sha256 IS DISTINCT FROM encode(sha256(convert_to(a.body_text,'UTF8')),'hex') THEN RAISE EXCEPTION 'feedback v2 invalid frozen source'; END IF;
 d:=a.body_text::jsonb; s:=d->'sample';
 IF d->>'schema_version' IS DISTINCT FROM '2' OR d->>'sample_key' !~ '^[0-9a-f]{64}$' OR jsonb_array_length(s->'comments') NOT BETWEEN 1 AND 20
 OR s->>'business_code' IS DISTINCT FROM t.business_code OR NOT EXISTS(SELECT 1 FROM snapshot_entries se JOIN intelligence_snapshots snap ON snap.id=se.snapshot_id AND snap.org_id=se.org_id WHERE se.org_id=organization AND se.id=(s->>'entry_id')::uuid AND snap.id=(s->>'snapshot_id')::uuid AND snap.business_code=t.business_code AND snap.business_date=(s->>'business_date')::date AND snap.version_no=(s->>'snapshot_version')::int AND snap.source_id=t.source_id AND snap.sealed_at IS NOT NULL)
 OR NOT EXISTS(SELECT 1 FROM task_inputs i WHERE i.org_id=organization AND i.task_id=t.id AND i.ai_config_revision_id=(d->'config'->>'revision_id')::uuid)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(s->'comments') x LEFT JOIN comment_evidence ce ON ce.org_id=organization AND ce.id=(x->>'id')::uuid WHERE ce.id IS NULL OR ce.body_text IS DISTINCT FROM x->>'body_text' OR (ce.captured_at AT TIME ZONE 'Asia/Shanghai')::date IS DISTINCT FROM (s->>'business_date')::date OR NOT EXISTS(SELECT 1 FROM task_inputs i WHERE i.org_id=organization AND i.task_id=t.id AND i.raw_asset_id=ce.raw_asset_id)) THEN RAISE EXCEPTION 'feedback v2 invalid sample linkage'; END IF;
 IF EXISTS(SELECT 1 FROM ai_executions ex WHERE ex.org_id=organization AND ex.task_id=t.id AND (ex.invocation_no<>1 OR ex.config_revision_id IS DISTINCT FROM (d->'config'->>'revision_id')::uuid OR ex.input_manifest_file_id IS NULL)) THEN RAISE EXCEPTION 'feedback v2 invalid execution'; END IF;
 SELECT * INTO f FROM feedback_snapshots WHERE org_id=organization AND task_id=t.id;
 IF f.id IS NULL THEN
 IF t.state='succeeded' THEN RAISE EXCEPTION 'feedback v2 missing result'; END IF;
 CONTINUE; END IF;
 SELECT * INTO e FROM ai_executions WHERE org_id=organization AND id=f.ai_execution_id;
 IF e.task_id IS DISTINCT FROM t.id OR e.result_state IS DISTINCT FROM 'completed' OR e.output_file_id IS NULL OR f.snapshot_id IS DISTINCT FROM (s->>'snapshot_id')::uuid
 OR f.sample_count<>jsonb_array_length(s->'comments')
 OR (f.classified_count=0 AND (f.summary IS NOT NULL OR EXISTS(SELECT 1 FROM feedback_claims cl WHERE cl.org_id=organization AND cl.feedback_id=f.id AND (cl.kind<>'emotion' OR cl.details->>'sentiment' IS DISTINCT FROM 'unclassifiable'))))
 OR (f.classified_count>0 AND (f.summary IS NULL OR btrim(f.summary)=''))
 OR (t.state='succeeded' AND ((SELECT count(*) FROM task_outputs o WHERE o.org_id=organization AND o.task_id=t.id)<>2 OR NOT EXISTS(SELECT 1 FROM task_outputs o WHERE o.org_id=organization AND o.task_id=t.id AND o.feedback_id=f.id) OR NOT EXISTS(SELECT 1 FROM task_outputs o WHERE o.org_id=organization AND o.task_id=t.id AND o.ai_execution_id=e.id)))
 OR EXISTS(SELECT 1 FROM feedback_comments fc WHERE fc.org_id=organization AND fc.feedback_id=f.id AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(s->'comments') x WHERE (x->>'id')::uuid=fc.comment_id))
 OR EXISTS(SELECT 1 FROM feedback_claims cl WHERE cl.org_id=organization AND cl.feedback_id=f.id AND cl.kind='emotion' AND (cl.details->>'sentiment' IS NULL OR cl.details->>'sentiment' NOT IN ('positive','negative','neutral','mixed','unclassifiable')))
 OR EXISTS(SELECT 1 FROM feedback_comments fc WHERE fc.org_id=organization AND fc.feedback_id=f.id AND NOT EXISTS(SELECT 1 FROM feedback_claim_evidence ce JOIN feedback_claims cl ON cl.id=ce.claim_id AND cl.org_id=ce.org_id WHERE ce.org_id=organization AND ce.feedback_id=f.id AND ce.comment_id=fc.comment_id AND cl.kind='emotion'))
 OR EXISTS(SELECT 1 FROM feedback_claim_evidence ce JOIN feedback_claims cl ON cl.id=ce.claim_id AND cl.org_id=ce.org_id WHERE ce.org_id=organization AND ce.feedback_id=f.id AND cl.kind='emotion' GROUP BY ce.comment_id HAVING count(DISTINCT cl.details->>'sentiment')>1)
 THEN RAISE EXCEPTION 'feedback v2 invalid result closure'; END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON tasks DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON task_inputs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON task_outputs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON task_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON ai_executions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON raw_assets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON feedback_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON feedback_comments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON feedback_claims DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
CREATE CONSTRAINT TRIGGER zz_feedback_v2 AFTER INSERT OR UPDATE OR DELETE ON feedback_claim_evidence DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_feedback_v2_guard();
