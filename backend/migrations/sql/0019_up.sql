-- Preserve immutable failed HTTP outcomes; accept only an exact sealed zero-I/O recovery.
DO $migration$
DECLARE definition text; old_text text; new_text text;
BEGIN
SELECT pg_get_functiondef('cip_validate()'::regprocedure) INTO definition;
old_text := $old$NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success')$old$;
new_text := $new$(NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success') AND NOT EXISTS(SELECT 1 FROM collection_calls hc
 JOIN raw_assets hr ON hr.org_id=hc.org_id AND hr.collection_call_id=hc.id AND hr.collection_job_id=hc.job_id
 JOIN task_inputs hi ON hi.org_id=hr.org_id AND hi.raw_asset_id=hr.id AND hi.role='captured_response'
 JOIN tasks ht ON ht.org_id=hi.org_id AND ht.id=hi.task_id
 JOIN task_outputs ho ON ho.org_id=ht.org_id AND ho.task_id=ht.id AND ho.role='hongguo_offline_recovery'
 JOIN raw_assets hm ON hm.org_id=ho.org_id AND hm.id=ho.raw_asset_id
 JOIN sources hs ON hs.org_id=j.org_id AND hs.id=j.source_id
 WHERE hc.org_id=s.org_id AND hc.job_id=s.job_id AND hc.http_status=200 AND hc.outcome='invalid_shape'
 AND j.capability_code='hongguo.board' AND j.connector_version='hongguo-public-v1'
 AND j.plan_id IS NULL AND j.max_requests=1 AND j.max_items=20 AND hs.platform_code='hongguo' AND hs.target_kind='board'
 AND hs.board_code=j.safe_request->>'board' AND hs.board_code IN ('hot-drama','hot-real-drama','hot-ai-drama','hot-comic-drama')
 AND ht.kind='hongguo.recover' AND ht.handler_version='hongguo-public-v1' AND ht.state='succeeded'
 AND ht.max_external_calls=0 AND ht.max_attempts=1 AND ht.inputs_sealed_at IS NOT NULL AND ht.outputs_sealed_at IS NOT NULL
 AND ht.source_id=j.source_id AND ht.business_code=j.business_code
 AND hr.origin='api' AND hr.sha256=encode(sha256(convert_to(hr.body_text,'UTF8')),'hex')
 AND s.view_kind='board' AND s.entry_count BETWEEN 1 AND 20
 AND s.entry_count=(SELECT count(*) FROM snapshot_entries he WHERE he.org_id=s.org_id AND he.snapshot_id=s.id)
 AND NOT EXISTS(SELECT 1 FROM snapshot_entries he LEFT JOIN content_observations hv ON hv.org_id=he.org_id AND hv.id=he.content_observation_id
 LEFT JOIN external_contents hx ON hx.org_id=hv.org_id AND hx.id=hv.content_id
 WHERE he.org_id=s.org_id AND he.snapshot_id=s.id AND (he.account_observation_id IS NOT NULL OR hv.raw_asset_id IS DISTINCT FROM hr.id OR hx.platform_code IS DISTINCT FROM 'hongguo'))
 AND hm.origin='processing' AND hm.processing_task_id=ht.id AND hm.parent_raw_asset_id=hr.id
 AND hm.sha256=encode(sha256(convert_to(hm.body_text,'UTF8')),'hex')
 AND hm.body_text::jsonb=jsonb_build_object('source_raw_id',hr.id::text,'snapshot_id',s.id::text)))$new$;
IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>1 THEN RAISE EXCEPTION 'unexpected reparse provenance guard'; END IF;
EXECUTE replace(definition,old_text,new_text);
END $migration$;
