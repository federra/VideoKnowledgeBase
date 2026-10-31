DO $migration$
DECLARE definition text; old_text text; new_text text;
BEGIN
 SELECT pg_get_functiondef('cip_validate()'::regprocedure) INTO definition;
 old_text := $old$(NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success') AND NOT cip_hongguo_saved_allowed(s.org_id,s.job_id))$old$;
 new_text := $new$NOT EXISTS(SELECT 1 FROM collection_calls c WHERE c.job_id=j.id AND c.outcome='success')$new$;
 IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>1 THEN RAISE EXCEPTION 'unexpected 0026 provenance guard'; END IF;
 definition := replace(definition,old_text,new_text);
 old_text := $old$(r.collection_job_id IS DISTINCT FROM s.job_id AND NOT cip_page_reuse_allowed(s.org_id,s.job_id,r.id) AND NOT cip_hongguo_saved_allowed(s.org_id,s.job_id,r.id))$old$;
 new_text := $new$r.collection_job_id IS DISTINCT FROM s.job_id$new$;
 IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>1 THEN RAISE EXCEPTION 'unexpected 0026 provenance guard'; END IF;
 definition := replace(definition,old_text,new_text);
 EXECUTE definition;
END $migration$;
DROP FUNCTION cip_page_reuse_allowed(uuid,uuid,uuid);
DROP FUNCTION cip_hongguo_saved_allowed(uuid,uuid,uuid);
