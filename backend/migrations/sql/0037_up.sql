-- No client-writable settings or temp objects may authorize a skipped check.
CREATE SCHEMA cip_integrity_runtime;
REVOKE ALL ON SCHEMA cip_integrity_runtime FROM PUBLIC;
CREATE TABLE cip_integrity_runtime.validation_state (
 org_id uuid PRIMARY KEY REFERENCES public.organizations(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
 xid xid8 NOT NULL,
 generation bigint NOT NULL,
 integrity_generation bigint NOT NULL DEFAULT -1,
 relationships_generation bigint NOT NULL DEFAULT -1,
 integrity_runs bigint NOT NULL DEFAULT 0,
 relationships_runs bigint NOT NULL DEFAULT 0
);
CREATE TABLE cip_integrity_runtime.function_backup (
 name text PRIMARY KEY, definition text NOT NULL, owner_oid oid NOT NULL,
 acl aclitem[], applied_acl aclitem[], config text[], security_definer boolean NOT NULL
);
REVOKE ALL ON ALL TABLES IN SCHEMA cip_integrity_runtime FROM PUBLIC;
INSERT INTO cip_integrity_runtime.function_backup(name,definition,owner_oid,acl,config,security_definer)
 SELECT proname,pg_get_functiondef(oid),proowner,proacl,proconfig,prosecdef
 FROM pg_proc WHERE oid IN('public.cip_write_lock()'::regprocedure,'public.cip_validate()'::regprocedure,'public.cip_relationships()'::regprocedure,'public.cip_hongguo_saved_allowed(uuid,uuid,uuid)'::regprocedure);
DO $migration$
DECLARE definition text; prefix text; original text; replacement text; local_check text; metadata_only text;
BEGIN
 metadata_only:=$metadata$ IF TG_TABLE_NAME='audit_events' THEN RETURN NULL; END IF;
 IF TG_TABLE_NAME='task_attempts' AND TG_OP='UPDATE' THEN
  IF (to_jsonb(OLD)->>'finished_at') IS NULL AND (to_jsonb(NEW)->>'finished_at') IS NULL
   AND (to_jsonb(NEW)-'lease_expires_at') IS NOT DISTINCT FROM (to_jsonb(OLD)-'lease_expires_at')
   AND (to_jsonb(NEW)->>'lease_expires_at')::timestamptz >= (to_jsonb(OLD)->>'lease_expires_at')::timestamptz
  THEN RETURN NULL; END IF;
 END IF;
$metadata$;
 -- JSON casts must not fail on unrelated HTML rows before source predicates filter them.
 SELECT b.definition INTO original FROM cip_integrity_runtime.function_backup b WHERE b.name='cip_hongguo_saved_allowed';
 IF strpos(original,'r.body_text::jsonb')=0 THEN RAISE EXCEPTION '0037 missing saved-capture JSON guard'; END IF;
 definition:=replace(original,'RETURN EXISTS(SELECT 1 FROM collection_jobs j',
 'RETURN EXISTS(WITH selected_raw AS MATERIALIZED (SELECT r.* FROM public.collection_jobs sj JOIN public.task_inputs si ON si.org_id=sj.org_id AND si.task_id=sj.task_id AND si.role=''hongguo_saved_capture'' JOIN public.raw_assets r ON r.org_id=si.org_id AND r.id=si.raw_asset_id WHERE sj.org_id=o AND sj.id=j_id AND (r_id IS NULL OR r.id=r_id)) SELECT 1 FROM collection_jobs j');
 IF definition=original THEN RAISE EXCEPTION '0037 unexpected saved-capture query'; END IF;
 definition:=replace(definition,'JOIN raw_assets r ON r.org_id=i.org_id AND r.id=i.raw_asset_id','JOIN selected_raw r ON r.org_id=i.org_id AND r.id=i.raw_asset_id');
 EXECUTE replace(definition,'r.body_text::jsonb','(CASE WHEN r.body_text IS JSON OBJECT THEN r.body_text::jsonb ELSE NULL END)');
 SELECT b.definition INTO original FROM cip_integrity_runtime.function_backup b WHERE b.name='cip_write_lock';
 definition:=original;
 prefix:=' PERFORM pg_advisory_xact_lock(hashtextextended(''cip:b1:''||o::text,0));';
 IF strpos(definition,prefix)=0 THEN RAISE EXCEPTION '0037 unexpected write lock definition'; END IF;
 replacement:=prefix||E'\n IF o IS NOT NULL THEN\n INSERT INTO cip_integrity_runtime.validation_state AS v(org_id,xid,generation) VALUES(o,pg_current_xact_id(),1)\n ON CONFLICT(org_id) DO UPDATE SET xid=EXCLUDED.xid,\n generation=CASE WHEN v.xid=EXCLUDED.xid THEN v.generation+1 ELSE 1 END,\n integrity_generation=CASE WHEN v.xid=EXCLUDED.xid THEN v.integrity_generation ELSE -1 END,\n relationships_generation=CASE WHEN v.xid=EXCLUDED.xid THEN v.relationships_generation ELSE -1 END,\n integrity_runs=CASE WHEN v.xid=EXCLUDED.xid THEN v.integrity_runs ELSE 0 END,\n relationships_runs=CASE WHEN v.xid=EXCLUDED.xid THEN v.relationships_runs ELSE 0 END;\n END IF;';
 EXECUTE replace(definition,prefix,replacement);
 ALTER FUNCTION public.cip_write_lock() SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp;

 SELECT b.definition INTO original FROM cip_integrity_runtime.function_backup b WHERE b.name='cip_validate';
 definition:=original;
 -- Preserve the per-row sealed-object check even when the global generation is validated.
 local_check:=E' IF TG_TABLE_NAME IN (''intelligence_snapshots'',''feedback_snapshots'',''artifact_versions'',''research_submissions'',''input_sets'',''analysis_reports'',''quality_evaluations'',''predictions'',''knowledge_revisions'') THEN\n   EXECUTE format(''SELECT sealed_at FROM %I WHERE id=$1'',TG_TABLE_NAME) INTO stamp USING (row_data->>''id'')::uuid;\n   IF stamp IS NULL THEN RAISE EXCEPTION ''unsealed % cannot commit'',TG_TABLE_NAME; END IF;\n END IF;';
 IF strpos(definition,local_check)=0 THEN RAISE EXCEPTION '0037 unexpected sealed-row check'; END IF;
 definition:=replace(definition,local_check,'');
 prefix:=' IF o IS NULL THEN RETURN NULL; END IF;';
 IF strpos(definition,prefix)=0 THEN RAISE EXCEPTION '0037 missing integrity entry'; END IF;
 IF strpos(original,'audit_events')>0 THEN RAISE EXCEPTION '0037 audit dependency requires review'; END IF;
 replacement:=prefix||E'\n'||replace(local_check,'FROM %I','FROM public.%I')||E'\n'||metadata_only||E' IF EXISTS(SELECT 1 FROM cip_integrity_runtime.validation_state WHERE org_id=o AND xid=pg_current_xact_id() AND integrity_generation=generation) AND EXISTS(SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid=TG_RELID AND tgfoid=''public.cip_write_lock()''::regprocedure AND tgenabled IN (''O'',''A'') AND (tgtype::integer & 31)=31 AND tgqual IS NULL AND tgattr=''''::int2vector) THEN RETURN NULL; END IF;';
 definition:=replace(definition,prefix,replacement);
 definition:=replace(definition,E' RETURN NULL;\nEND ',E' UPDATE cip_integrity_runtime.validation_state SET integrity_generation=generation,integrity_runs=integrity_runs+1 WHERE org_id=o AND xid=pg_current_xact_id();\n RETURN NULL;\nEND ');
 EXECUTE definition;
 ALTER FUNCTION public.cip_validate() SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp;

 SELECT b.definition INTO original FROM cip_integrity_runtime.function_backup b WHERE b.name='cip_relationships';
 definition:=original;
 prefix:=' o:=(body->>''org_id'')::uuid;';
 IF strpos(definition,prefix)=0 THEN RAISE EXCEPTION '0037 missing relationship entry'; END IF;
 IF strpos(original,'audit_events')>0 THEN RAISE EXCEPTION '0037 audit relationship dependency requires review'; END IF;
 definition:=replace(definition,prefix,prefix||E'\n'||metadata_only||E' IF EXISTS(SELECT 1 FROM cip_integrity_runtime.validation_state WHERE org_id=o AND xid=pg_current_xact_id() AND relationships_generation=generation) AND EXISTS(SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid=TG_RELID AND tgfoid=''public.cip_write_lock()''::regprocedure AND tgenabled IN (''O'',''A'') AND (tgtype::integer & 31)=31 AND tgqual IS NULL AND tgattr=''''::int2vector) THEN RETURN NULL; END IF;');
 definition:=replace(definition,E' RETURN NULL;\nEND ',E' UPDATE cip_integrity_runtime.validation_state SET relationships_generation=generation,relationships_runs=relationships_runs+1 WHERE org_id=o AND xid=pg_current_xact_id();\n RETURN NULL;\nEND ');
 EXECUTE definition;
 ALTER FUNCTION public.cip_relationships() SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp;
END $migration$;
REVOKE EXECUTE ON FUNCTION public.cip_write_lock(),public.cip_validate(),public.cip_relationships() FROM PUBLIC;
-- Stock validation deliberately has no dirty-state writer: missing state always checks.
CREATE TEMP TABLE cip_0037_stock(org_id uuid NOT NULL) ON COMMIT DROP;
CREATE CONSTRAINT TRIGGER stock_integrity AFTER INSERT ON cip_0037_stock DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.cip_validate();
CREATE CONSTRAINT TRIGGER stock_relationships AFTER INSERT ON cip_0037_stock DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.cip_relationships();
INSERT INTO cip_0037_stock SELECT id FROM public.organizations;
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

UPDATE cip_integrity_runtime.function_backup b SET applied_acl=coalesce(p.proacl,acldefault('f',p.proowner)) FROM pg_proc p WHERE p.oid=CASE WHEN b.name='cip_hongguo_saved_allowed' THEN 'public.cip_hongguo_saved_allowed(uuid,uuid,uuid)'::regprocedure ELSE ('public.'||b.name||'()')::regprocedure END;
