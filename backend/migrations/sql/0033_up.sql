-- Additive typed explanations over sealed Task manifests; no new tables or privileges.
CREATE FUNCTION cip_genre_explanation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE row_data jsonb; organization uuid; identity uuid; identities uuid[];
 t tasks%ROWTYPE; source raw_assets%ROWTYPE; result raw_assets%ROWTYPE;
 execution ai_executions%ROWTYPE; output_file file_objects%ROWTYPE;
 frozen jsonb; target jsonb; response jsonb; item jsonb; n integer;
BEGIN
 row_data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 organization := (row_data->>'org_id')::uuid;
 IF TG_TABLE_NAME='tasks' THEN identities:=ARRAY[(row_data->>'id')::uuid];
 ELSIF TG_TABLE_NAME IN ('task_inputs','task_outputs','ai_executions','task_attempts') THEN
   identities:=ARRAY[(row_data->>'task_id')::uuid];
 ELSE
   SELECT array_agg(id) INTO identities FROM tasks WHERE org_id=organization
    AND kind='knowledge.genre_explain' AND
    (raw_asset_id=(row_data->>'id')::uuid OR id=(row_data->>'processing_task_id')::uuid);
 END IF;
 FOREACH identity IN ARRAY coalesce(identities,'{}'::uuid[]) LOOP
  SELECT * INTO t FROM tasks WHERE org_id=organization AND id=identity;
  IF t.kind IS DISTINCT FROM 'knowledge.genre_explain' THEN CONTINUE; END IF;
  SELECT * INTO source FROM raw_assets WHERE org_id=organization AND id=t.raw_asset_id;
  IF t.handler_version IS DISTINCT FROM '1' OR t.max_attempts IS DISTINCT FROM 1
   OR t.max_external_calls IS DISTINCT FROM 1 OR t.business_code IS DISTINCT FROM 'motion_comic'
   OR t.execution_authorized_by IS NULL OR t.requested_by IS NULL
   OR source.origin IS DISTINCT FROM 'manual' OR source.asset_kind IS DISTINCT FROM 'response'
   OR source.submitted_by IS DISTINCT FROM t.execution_authorized_by OR source.body_text IS NULL
   OR source.sha256 IS DISTINCT FROM encode(sha256(convert_to(source.body_text,'UTF8')),'hex') THEN
    RAISE EXCEPTION 'genre explanation invalid task or frozen source';
  END IF;
  frozen:=source.body_text::jsonb;
  IF jsonb_typeof(frozen) IS DISTINCT FROM 'object'
   OR frozen->'schema_version' IS DISTINCT FROM '1'::jsonb
   OR frozen->>'business_code' IS DISTINCT FROM 'motion_comic'
   OR frozen->>'source_reuse' IS DISTINCT FROM 'user_authorized_existing_topic_source'
   OR jsonb_typeof(frozen->'reason') IS DISTINCT FROM 'string'
   OR (frozen->>'reason') !~ '[^[:space:]]' OR jsonb_typeof(frozen->'targets') IS DISTINCT FROM 'array'
   OR jsonb_typeof(frozen->'config') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'genre explanation invalid frozen manifest';
  END IF;
  n:=jsonb_array_length(frozen->'targets');
  IF n NOT BETWEEN 1 AND 20
   OR (SELECT count(DISTINCT value->>'revision_id') FROM jsonb_array_elements(frozen->'targets'))<>n
   OR (SELECT count(*) FROM task_inputs WHERE org_id=organization AND task_id=t.id)<>n+2
   OR (SELECT count(*) FROM task_inputs WHERE org_id=organization AND task_id=t.id
      AND role='freeze' AND raw_asset_id=t.raw_asset_id)<>1
   OR (SELECT count(*) FROM task_inputs WHERE org_id=organization AND task_id=t.id
      AND role='model' AND ai_config_revision_id::text=frozen->'config'->>'revision_id')<>1
   OR (SELECT count(*) FROM task_inputs WHERE org_id=organization AND task_id=t.id
      AND role='target' AND knowledge_revision_id IS NOT NULL)<>n THEN
    RAISE EXCEPTION 'genre explanation frozen input binding mismatch';
  END IF;
  FOR target IN SELECT value FROM jsonb_array_elements(frozen->'targets') LOOP
   IF jsonb_typeof(target) IS DISTINCT FROM 'object'
    OR NOT EXISTS(SELECT 1 FROM task_inputs WHERE org_id=organization AND task_id=t.id
      AND role='target' AND knowledge_revision_id::text=target->>'revision_id') THEN
     RAISE EXCEPTION 'genre explanation frozen revision mismatch';
   END IF;
   IF t.state='succeeded' AND NOT EXISTS(
     SELECT 1 FROM knowledge_revisions r
     JOIN knowledge_publications p ON p.org_id=r.org_id AND p.revision_id=r.id
     JOIN knowledge_items k ON k.org_id=r.org_id AND k.id=r.knowledge_id
     WHERE r.org_id=organization AND r.id::text=target->>'revision_id'
      AND r.knowledge_id::text=target->>'knowledge_id' AND p.id::text=target->>'publication_id'
      AND p.knowledge_id=k.id AND k.published_publication_id=p.id
      AND k.recycled_at IS NULL AND k.purged_at IS NULL
      AND r.browse_category='genre' AND r.sealed_at IS NOT NULL
      AND r.title=target->>'title' AND r.tags=target->'tags'
      AND EXISTS(SELECT 1 FROM knowledge_businesses b WHERE b.org_id=r.org_id
         AND b.revision_id=r.id AND b.business_code='motion_comic')) THEN
     RAISE EXCEPTION 'genre explanation target is not exact current published genre';
   END IF;
  END LOOP;
  IF (SELECT count(*) FROM ai_executions WHERE org_id=organization AND task_id=t.id)>1
   OR (SELECT count(*) FROM task_attempts WHERE org_id=organization AND task_id=t.id)>1
   OR EXISTS(SELECT 1 FROM ai_executions e JOIN task_attempts a ON a.org_id=e.org_id AND a.id=e.attempt_id
      WHERE e.org_id=organization AND e.task_id=t.id AND
      (a.task_id<>t.id OR a.attempt_no<>1 OR e.invocation_no<>1
       OR e.config_revision_id::text IS DISTINCT FROM frozen->'config'->>'revision_id')) THEN
    RAISE EXCEPTION 'genre explanation attempt execution config mismatch';
  END IF;
  IF t.state<>'succeeded' THEN
   IF EXISTS(SELECT 1 FROM task_outputs WHERE org_id=organization AND task_id=t.id) THEN
    RAISE EXCEPTION 'genre explanation output requires succeeded task';
   END IF;
   CONTINUE;
  END IF;
  SELECT r.* INTO result FROM task_outputs o JOIN raw_assets r ON r.org_id=o.org_id AND r.id=o.raw_asset_id
    WHERE o.org_id=organization AND o.task_id=t.id AND o.role='genre_explanations';
  SELECT e.* INTO execution FROM task_outputs o JOIN ai_executions e ON e.org_id=o.org_id AND e.id=o.ai_execution_id
    WHERE o.org_id=organization AND o.task_id=t.id AND o.role='model';
  SELECT * INTO output_file FROM file_objects WHERE org_id=organization AND id=execution.output_file_id;
  IF (SELECT count(*) FROM task_outputs WHERE org_id=organization AND task_id=t.id)<>2
   OR (SELECT count(*) FROM task_outputs WHERE org_id=organization AND task_id=t.id
      AND role='genre_explanations' AND raw_asset_id IS NOT NULL)<>1
   OR (SELECT count(*) FROM task_outputs WHERE org_id=organization AND task_id=t.id
      AND role='model' AND ai_execution_id IS NOT NULL)<>1
   OR (SELECT count(*) FROM ai_executions WHERE org_id=organization AND task_id=t.id)<>1
   OR (SELECT count(*) FROM task_attempts WHERE org_id=organization AND task_id=t.id)<>1
   OR result.origin IS DISTINCT FROM 'processing' OR result.asset_kind IS DISTINCT FROM 'response'
   OR result.processing_task_id IS DISTINCT FROM t.id OR result.parent_raw_asset_id IS DISTINCT FROM source.id
   OR result.parent_artifact_version_id IS NOT NULL OR result.body_text IS NULL
   OR execution.task_id IS DISTINCT FROM t.id OR execution.result_state IS DISTINCT FROM 'completed'
   OR execution.invocation_no IS DISTINCT FROM 1
   OR execution.config_revision_id::text IS DISTINCT FROM frozen->'config'->>'revision_id'
   OR NOT EXISTS(SELECT 1 FROM task_attempts a WHERE a.org_id=organization AND a.id=execution.attempt_id
      AND a.task_id=t.id AND a.attempt_no=1 AND a.outcome='succeeded')
   OR output_file.validation_state IS DISTINCT FROM 'accepted'
   OR result.sha256 IS DISTINCT FROM output_file.sha256
   OR result.sha256 IS DISTINCT FROM encode(sha256(convert_to(result.body_text,'UTF8')),'hex')
   OR output_file.byte_size IS DISTINCT FROM octet_length(result.body_text)::bigint THEN
    RAISE EXCEPTION 'genre explanation output execution file or digest mismatch';
  END IF;
  response:=result.body_text::jsonb;
  IF jsonb_typeof(response) IS DISTINCT FROM 'object'
   OR (SELECT count(*) FROM jsonb_object_keys(response))<>1
   OR jsonb_typeof(response->'items') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'genre explanation invalid output object';
  END IF;
  IF jsonb_array_length(response->'items')<>n
   OR (SELECT count(DISTINCT value->>'revision_id') FROM jsonb_array_elements(response->'items'))<>n THEN
    RAISE EXCEPTION 'genre explanation output target coverage mismatch';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(response->'items') LOOP
   IF jsonb_typeof(item) IS DISTINCT FROM 'object'
    OR (SELECT count(*) FROM jsonb_object_keys(item))<>2
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(frozen->'targets') x WHERE x->>'revision_id'=item->>'revision_id')
    OR jsonb_typeof(item->'explanation') IS DISTINCT FROM 'string'
    OR item->>'explanation' IS DISTINCT FROM btrim(item->>'explanation')
    OR (item->>'explanation') ~ '^[[:space:]]|[[:space:]]$'
    OR char_length(item->>'explanation') NOT BETWEEN 1 AND 180
    OR item->>'explanation' !~ '[一-鿿]'
    OR item->>'explanation' !~ E'^[^。！？!?\\r\\n]+。$' THEN
     RAISE EXCEPTION 'genre explanation invalid sentence or revision';
   END IF;
  END LOOP;
 END LOOP;
 RETURN NULL;
EXCEPTION WHEN invalid_text_representation THEN
 RAISE EXCEPTION 'genre explanation invalid JSON or identifier';
END $$;
CREATE CONSTRAINT TRIGGER zz_genre_explanation AFTER INSERT OR UPDATE ON tasks
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_genre_explanation_guard();
CREATE CONSTRAINT TRIGGER zz_genre_explanation AFTER INSERT OR UPDATE OR DELETE ON task_inputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_genre_explanation_guard();
CREATE CONSTRAINT TRIGGER zz_genre_explanation AFTER INSERT OR UPDATE OR DELETE ON task_outputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_genre_explanation_guard();
CREATE CONSTRAINT TRIGGER zz_genre_explanation AFTER INSERT OR UPDATE ON raw_assets
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_genre_explanation_guard();
CREATE CONSTRAINT TRIGGER zz_genre_explanation AFTER INSERT OR UPDATE ON ai_executions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_genre_explanation_guard();
CREATE CONSTRAINT TRIGGER zz_genre_explanation AFTER INSERT OR UPDATE ON task_attempts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_genre_explanation_guard();
