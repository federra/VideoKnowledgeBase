-- Narrow manual-import exception; all existing provider provenance remains enforced.
DO $migration$
DECLARE definition text; old_text text; new_text text;
BEGIN

 SELECT pg_get_functiondef('cip_validate()'::regprocedure) INTO definition;
 old_text := $old$NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success')$old$;
 new_text := $new$(NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success') AND NOT EXISTS(SELECT 1 FROM collection_jobs mj JOIN tasks mt ON mt.org_id=mj.org_id AND mt.id=mj.task_id
 JOIN task_inputs mi ON mi.org_id=mt.org_id AND mi.task_id=mt.id AND mi.role='novel_saved_html'
 JOIN raw_assets mr ON mr.org_id=mi.org_id AND mr.id=mi.raw_asset_id
 JOIN sources ms ON ms.org_id=mj.org_id AND ms.id=mj.source_id
 WHERE mj.org_id=s.org_id AND mj.id=s.job_id AND mt.kind='collect.novels' AND mt.max_external_calls=0
 AND mj.capability_code='novel.qidian.board' AND mj.plan_id IS NULL AND ms.platform_code='qidian'
 AND mj.safe_request->>'method'='qidian-desktop-html-v1' AND mj.safe_request->>'gender'='female'
 AND mj.safe_request->>'capture_kind'='user_saved_html' AND mj.safe_request->>'raw_asset_id'=mr.id::text
 AND mj.safe_request->>'file_sha256'=mr.sha256 AND mr.sha256=encode(sha256(convert_to(mr.body_text,'UTF8')),'hex')
 AND mr.origin='manual' AND mr.asset_kind='response' AND mr.submitted_by=mt.requested_by
 AND (mr.captured_at AT TIME ZONE 'Asia/Shanghai')::date=mj.business_date
 AND NOT EXISTS(SELECT 1 FROM collection_calls mc WHERE mc.org_id=mj.org_id AND mc.job_id=mj.id)))$new$;
 IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>1 THEN RAISE EXCEPTION 'unexpected provenance guard definition'; END IF;
 definition := replace(definition,old_text,new_text);
 old_text := $old$r.collection_job_id IS DISTINCT FROM s.job_id$old$;
 new_text := $new$(r.collection_job_id IS DISTINCT FROM s.job_id AND NOT EXISTS(SELECT 1 FROM collection_jobs mj JOIN tasks mt ON mt.org_id=mj.org_id AND mt.id=mj.task_id
 JOIN task_inputs mi ON mi.org_id=mt.org_id AND mi.task_id=mt.id AND mi.role='novel_saved_html'
 JOIN raw_assets mr ON mr.org_id=mi.org_id AND mr.id=mi.raw_asset_id
 JOIN sources ms ON ms.org_id=mj.org_id AND ms.id=mj.source_id
 WHERE mj.org_id=s.org_id AND mj.id=s.job_id AND mt.kind='collect.novels' AND mt.max_external_calls=0
 AND mj.capability_code='novel.qidian.board' AND mj.plan_id IS NULL AND ms.platform_code='qidian'
 AND mj.safe_request->>'method'='qidian-desktop-html-v1' AND mj.safe_request->>'gender'='female'
 AND mj.safe_request->>'capture_kind'='user_saved_html' AND mj.safe_request->>'raw_asset_id'=mr.id::text
 AND mj.safe_request->>'file_sha256'=mr.sha256 AND mr.sha256=encode(sha256(convert_to(mr.body_text,'UTF8')),'hex')
 AND mr.origin='manual' AND mr.asset_kind='response' AND mr.submitted_by=mt.requested_by
 AND (mr.captured_at AT TIME ZONE 'Asia/Shanghai')::date=mj.business_date
 AND NOT EXISTS(SELECT 1 FROM collection_calls mc WHERE mc.org_id=mj.org_id AND mc.job_id=mj.id) AND mr.id=r.id))$new$;
 IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>1 THEN RAISE EXCEPTION 'unexpected provenance guard definition'; END IF;
 definition := replace(definition,old_text,new_text);
 EXECUTE definition;
END $migration$;
