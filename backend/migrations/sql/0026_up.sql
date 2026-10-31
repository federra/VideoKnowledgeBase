-- Exact same-day page continuation and explicit authorized Hongguo capture.
CREATE FUNCTION cip_page_reuse_allowed(o uuid, j_id uuid, r_id uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $fn$
 SELECT EXISTS(SELECT 1 FROM collection_jobs j
 JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id
 JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id AND i.role='collection_page_reuse' AND i.raw_asset_id=r_id
 JOIN raw_assets r ON r.org_id=i.org_id AND r.id=i.raw_asset_id
 JOIN collection_calls c ON c.org_id=r.org_id AND c.id=r.collection_call_id AND c.job_id=r.collection_job_id
 JOIN collection_jobs old ON old.org_id=r.org_id AND old.id=r.collection_job_id
 JOIN tasks ot ON ot.org_id=old.org_id AND ot.id=old.task_id
 JOIN task_inputs mi ON mi.org_id=t.org_id AND mi.task_id=t.id AND mi.role='collection_resume_manifest'
 JOIN raw_assets m ON m.org_id=mi.org_id AND m.id=mi.raw_asset_id
 JOIN collection_jobs parent ON parent.org_id=j.org_id AND parent.id=(m.body_text::jsonb->>'original_job')::uuid
 JOIN tasks pt ON pt.org_id=parent.org_id AND pt.id=parent.task_id
 WHERE j.org_id=o AND j.id=j_id AND j.id<>old.id AND j.plan_id IS NULL AND old.plan_id IS NULL
 AND t.inputs_sealed_at IS NOT NULL AND t.max_attempts=1 AND t.max_external_calls=j.max_requests
 AND t.handler_version=j.connector_version AND t.business_code=j.business_code AND t.source_id=j.source_id
 AND ((j.capability_code='douyin.creator.posts' AND j.connector_version='douyin-creator-posts-v1'
 AND j.max_requests=60 AND j.max_items=1200 AND t.kind='collect.creator-posts.resume' AND ot.kind IN ('collect.creator-posts','collect.creator-posts.resume'))
 OR (j.capability_code='douyin.search.microfilm' AND j.connector_version='douyin-microfilm-search-v1'
 AND j.max_requests=112 AND j.max_items=50 AND t.kind='collect.microfilm.resume' AND ot.kind IN ('collect.microfilm','collect.microfilm.resume')))
 AND parent.source_id=j.source_id AND parent.connection_id=j.connection_id AND parent.business_code=j.business_code
 AND parent.business_date=j.business_date AND parent.capability_code=j.capability_code AND parent.connector_version=j.connector_version
 AND parent.safe_request=j.safe_request AND parent.request_sha256=j.request_sha256
 AND parent.max_requests=j.max_requests AND parent.max_items=j.max_items AND pt.state IN ('failed','succeeded')
 AND j.business_code='story_short' AND ot.handler_version=j.connector_version AND ot.state IN ('failed','succeeded') AND ot.inputs_sealed_at IS NOT NULL
 AND old.source_id=j.source_id AND old.connection_id=j.connection_id AND old.business_code=j.business_code
 AND old.business_date=j.business_date AND old.capability_code=j.capability_code AND old.connector_version=j.connector_version
 AND old.safe_request=j.safe_request AND old.request_sha256=j.request_sha256
 AND old.max_requests=j.max_requests AND old.max_items=j.max_items
 AND r.origin='api' AND c.outcome='success' AND c.http_status=200 AND c.completed_at IS NOT NULL
 AND (r.captured_at AT TIME ZONE 'Asia/Shanghai')::date=j.business_date
 AND r.sha256=encode(sha256(convert_to(r.body_text,'UTF8')),'hex')
 AND m.origin='manual' AND m.submitted_by=t.requested_by
 AND m.sha256=encode(sha256(convert_to(m.body_text,'UTF8')),'hex')
 AND m.body_text::jsonb->'pages' @> jsonb_build_array(jsonb_build_object('id',r.id::text,'sha256',r.sha256)));
$fn$;
CREATE FUNCTION cip_hongguo_saved_allowed(o uuid, j_id uuid, r_id uuid DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=public,pg_temp AS $fn$
BEGIN
 RETURN EXISTS(SELECT 1 FROM collection_jobs j
 JOIN tasks t ON t.org_id=j.org_id AND t.id=j.task_id
 JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id AND i.role='hongguo_saved_capture'
 JOIN raw_assets r ON r.org_id=i.org_id AND r.id=i.raw_asset_id
 JOIN sources s ON s.org_id=j.org_id AND s.id=j.source_id
 JOIN provider_connections pc ON pc.org_id=j.org_id AND pc.id=j.connection_id
 WHERE j.org_id=o AND j.id=j_id AND (r_id IS NULL OR r.id=r_id)
 AND j.capability_code='hongguo.board' AND j.connector_version='hongguo-public-v1'
 AND j.plan_id IS NULL AND j.max_requests=1 AND j.max_items=20
 AND t.kind='collect.hongguo.saved' AND t.handler_version=j.connector_version
 AND t.max_external_calls=0 AND t.max_attempts=1 AND t.inputs_sealed_at IS NOT NULL
 AND t.state='succeeded' AND t.outputs_sealed_at IS NOT NULL
 AND t.source_id=j.source_id AND t.business_code=j.business_code
 AND pc.provider_code='hongguo_public' AND pc.secret_ref='PUBLIC_HONGGUO_NO_SECRET'
 AND s.business_code=j.business_code AND s.platform_code='hongguo' AND s.target_kind='board' AND s.board_code=j.safe_request->>'board'
 AND s.board_code IN ('hot-drama','hot-real-drama','hot-ai-drama','hot-comic-drama')
 AND j.safe_request->>'method'='hongguo-saved-http-v1'
 AND j.safe_request->>'capture_kind'='authorized_http_capture'
 AND j.safe_request->>'raw_asset_id'=r.id::text AND j.safe_request->>'file_sha256'=r.sha256
 AND (SELECT count(*) FROM jsonb_object_keys(j.safe_request))=5
 AND r.origin='manual' AND r.asset_kind='response' AND r.submitted_by=t.requested_by
 AND r.sha256=encode(sha256(convert_to(r.body_text,'UTF8')),'hex')
 AND (r.captured_at AT TIME ZONE 'Asia/Shanghai')::date=j.business_date
 AND octet_length(decode(r.body_text::jsonb->>'html_base64','base64')) BETWEEN 1 AND 4194304
 AND r.body_text::jsonb->>'format'='hongguo-saved-http-v1'
 AND r.body_text::jsonb->>'response_sha256'=encode(sha256(decode(r.body_text::jsonb->>'html_base64','base64')),'hex')
 AND r.body_text::jsonb->'capture'->>'url'='https://hongguoduanju.com/rank/'||s.board_code
 AND r.body_text::jsonb->'capture'->'http_status'='200'::jsonb
 AND r.body_text::jsonb->'capture'->'body_complete'='true'::jsonb
 AND r.body_text::jsonb->'capture'->'text_available'='true'::jsonb
 AND r.body_text::jsonb->'capture'->>'sha256'=r.body_text::jsonb->>'response_sha256'
 AND r.body_text::jsonb->'capture'->>'body_sha256'=r.body_text::jsonb->>'response_sha256'
 AND r.body_text::jsonb->'capture'->>'body_representation'='httpx_decoded_bytes'
 AND r.body_text::jsonb->'capture'->>'content_type' IN ('text/html','application/xhtml+xml')
 AND (r.body_text::jsonb->'capture'->>'saved_bytes')::bigint=octet_length(decode(r.body_text::jsonb->>'html_base64','base64'))
 AND (r.body_text::jsonb->'capture'->>'received_bytes')::bigint=octet_length(decode(r.body_text::jsonb->>'html_base64','base64'))
 AND (r.body_text::jsonb->'capture'->>'captured_at')::timestamptz=r.captured_at
 AND (r.body_text::jsonb->'capture'->>'requested_at')::timestamptz<=r.captured_at
 AND COALESCE(r.body_text::jsonb->'capture'->>'collection_job_id','')=''
 AND COALESCE(r.body_text::jsonb->'capture'->>'failure_kind','')=''
 AND COALESCE(r.body_text::jsonb->'capture'->>'failure_stage','')=''
 AND COALESCE(r.body_text::jsonb->'capture'->>'exception_type','')=''
 AND NOT EXISTS(SELECT 1 FROM collection_calls cc WHERE cc.org_id=j.org_id AND cc.job_id=j.id));
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value OR datetime_field_overflow OR numeric_value_out_of_range THEN RETURN false;
END;
$fn$;
DO $migration$
DECLARE definition text; old_text text; new_text text;
BEGIN
 SELECT pg_get_functiondef('cip_validate()'::regprocedure) INTO definition;
 old_text := $old$r.collection_job_id IS DISTINCT FROM s.job_id$old$;
 new_text := $new$(r.collection_job_id IS DISTINCT FROM s.job_id AND NOT cip_page_reuse_allowed(s.org_id,s.job_id,r.id) AND NOT cip_hongguo_saved_allowed(s.org_id,s.job_id,r.id))$new$;
 IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>1 THEN RAISE EXCEPTION 'unexpected 0026 provenance guard'; END IF;
 definition := replace(definition,old_text,new_text);
 old_text := $old$NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success')$old$;
 new_text := $new$(NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success') AND NOT cip_hongguo_saved_allowed(s.org_id,s.job_id))$new$;
 IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>1 THEN RAISE EXCEPTION 'unexpected 0026 provenance guard'; END IF;
 definition := replace(definition,old_text,new_text);
 EXECUTE definition;
END $migration$;
