DO $migration$
DECLARE f record; current_owner oid; signature regprocedure;
BEGIN
 FOR f IN SELECT * FROM cip_integrity_runtime.function_backup ORDER BY name LOOP
  signature:=CASE WHEN f.name='cip_hongguo_saved_allowed' THEN 'public.cip_hongguo_saved_allowed(uuid,uuid,uuid)'::regprocedure ELSE ('public.'||f.name||'()')::regprocedure END;
  SELECT proowner INTO current_owner FROM pg_proc WHERE oid=signature;
  IF current_owner<>f.owner_oid THEN RAISE EXCEPTION '0037 function owner changed; inspect before downgrade'; END IF;
  IF EXISTS((SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=signature EXCEPT SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM aclexplode(f.applied_acl) a)) OR
   EXISTS((SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM aclexplode(f.applied_acl) a EXCEPT SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=signature)) THEN
   RAISE EXCEPTION '0037 function privileges changed; inspect before downgrade';
  END IF;
  EXECUTE f.definition;
  IF EXISTS(SELECT 1 FROM aclexplode(coalesce(f.acl,acldefault('f',f.owner_oid))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') THEN
   EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO PUBLIC',signature);
  ELSE EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC',signature);
  END IF;
  IF EXISTS(SELECT 1 FROM pg_proc WHERE oid=signature AND (proconfig IS DISTINCT FROM f.config OR prosecdef IS DISTINCT FROM f.security_definer)) OR
   EXISTS((SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=signature EXCEPT SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM aclexplode(coalesce(f.acl,acldefault('f',f.owner_oid))) a)) OR
   EXISTS((SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM aclexplode(coalesce(f.acl,acldefault('f',f.owner_oid))) a EXCEPT SELECT a.grantor,a.grantee,a.privilege_type,a.is_grantable FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=signature)) THEN
   RAISE EXCEPTION '0037 function attributes changed; downgrade rolled back';
  END IF;
 END LOOP;
END $migration$;
DROP TABLE cip_integrity_runtime.validation_state;
DROP TABLE cip_integrity_runtime.function_backup;
DROP SCHEMA cip_integrity_runtime;
