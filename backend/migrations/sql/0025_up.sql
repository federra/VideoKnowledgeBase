ALTER TABLE knowledge_items ADD COLUMN purged_at timestamptz;
ALTER TABLE knowledge_items ADD CONSTRAINT ck_knowledge_purged_recycled CHECK (purged_at IS NULL OR recycled_at IS NOT NULL);
CREATE INDEX ix_knowledge_retention_due ON knowledge_items(org_id,recycled_at,id) WHERE recycled_at IS NOT NULL AND purged_at IS NULL;

-- Only the narrow SECURITY DEFINER eraser may change sealed payloads. Ordinary
-- updates retain the original immutable-field and version protections.
CREATE FUNCTION cip_knowledge_retention_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE kid uuid; allowed text[]; old_body jsonb; new_body jsonb; privileged boolean;
BEGIN
 IF TG_TABLE_NAME='knowledge_items' THEN kid:=COALESCE(NEW.id,OLD.id);
 ELSIF TG_TABLE_NAME='knowledge_revisions' THEN kid:=COALESCE(NEW.knowledge_id,OLD.knowledge_id);
 ELSIF TG_TABLE_NAME='search_documents' THEN
  SELECT knowledge_id INTO kid FROM knowledge_publications WHERE org_id=OLD.org_id AND id=OLD.publication_id;
 ELSE
  SELECT p.knowledge_id INTO kid FROM search_documents d JOIN knowledge_publications p ON p.org_id=d.org_id AND p.id=d.publication_id WHERE d.org_id=OLD.org_id AND d.id=OLD.search_document_id;
 END IF;
 privileged:=current_user=(SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid=TG_RELID)
  AND current_setting('cip.purge_knowledge',true)=kid::text
  AND current_setting('cip.purge_org',true)=COALESCE(NEW.org_id,OLD.org_id)::text;
 IF privileged THEN
  IF TG_TABLE_NAME='knowledge_items' THEN
   IF TG_OP='UPDATE' AND OLD.recycled_at IS NOT NULL AND OLD.purged_at IS NULL AND NEW.purged_at IS NOT NULL
   AND NEW.title='[已永久删除]' AND NEW.lock_version=OLD.lock_version+1
   AND (to_jsonb(OLD)-ARRAY['title','purged_at','lock_version','updated_at'])=(to_jsonb(NEW)-ARRAY['title','purged_at','lock_version','updated_at']) THEN
    NEW.updated_at:=clock_timestamp(); RETURN NEW;
   END IF;
   RAISE EXCEPTION 'invalid permanent erasure identity';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM knowledge_items WHERE org_id=COALESCE(NEW.org_id,OLD.org_id) AND id=kid AND purged_at IS NOT NULL) THEN RAISE EXCEPTION 'invalid purge context'; END IF;
  IF TG_TABLE_NAME='knowledge_revisions' THEN
   IF TG_OP='UPDATE' AND NEW.title='[已永久删除]' AND NEW.body_text='[已永久删除]' AND NEW.tags='[]'::jsonb AND NEW.limitations IS NULL AND NEW.source_text IS NULL AND NEW.explanation IS NULL
   AND (to_jsonb(OLD)-ARRAY['title','body_text','tags','limitations','source_text','explanation'])=(to_jsonb(NEW)-ARRAY['title','body_text','tags','limitations','source_text','explanation']) THEN RETURN NEW; END IF;
   RAISE EXCEPTION 'invalid permanent erasure payload';
  END IF;
  IF TG_TABLE_NAME IN ('search_documents','embeddings') AND TG_OP='DELETE' THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'invalid permanent erasure operation';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.purged_at IS NOT NULL THEN RAISE EXCEPTION 'purged marker is protected'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable record cannot be deleted'; END IF;
 IF TG_TABLE_NAME='knowledge_items' THEN
  IF OLD.purged_at IS NOT NULL THEN RAISE EXCEPTION 'permanently erased knowledge is immutable'; END IF;
 END IF;
 allowed:=string_to_array(TG_ARGV[0],','); old_body:=to_jsonb(OLD); new_body:=to_jsonb(NEW);
 IF TG_ARGV[1]='sealed' THEN
  IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL THEN RAISE EXCEPTION 'sealed record is immutable'; END IF;
  NEW.sealed_at:=clock_timestamp();
 END IF;
 IF (old_body-allowed) IS DISTINCT FROM (new_body-allowed) THEN RAISE EXCEPTION 'immutable fields cannot change in %',TG_TABLE_NAME; END IF;
 IF old_body ? 'lock_version' THEN
  IF (new_body->>'lock_version')::bigint<>(old_body->>'lock_version')::bigint+1 THEN RAISE EXCEPTION 'VERSION_CONFLICT: lock_version must advance once'; END IF;
  NEW.updated_at:=clock_timestamp();
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER z_immutable ON knowledge_items;
CREATE TRIGGER z_immutable BEFORE INSERT OR UPDATE OR DELETE ON knowledge_items FOR EACH ROW EXECUTE FUNCTION cip_knowledge_retention_guard('title,owner_member_id,current_revision_id,published_publication_id,recycled_at,recycled_by,updated_at,lock_version','ordinary');
DROP TRIGGER z_immutable ON knowledge_revisions;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON knowledge_revisions FOR EACH ROW EXECUTE FUNCTION cip_knowledge_retention_guard('sealed_at','sealed');
DROP TRIGGER z_immutable ON search_documents;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON search_documents FOR EACH ROW EXECUTE FUNCTION cip_knowledge_retention_guard('document_text,search_vector,indexed_at','ordinary');
DROP TRIGGER z_immutable ON embeddings;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON embeddings FOR EACH ROW EXECUTE FUNCTION cip_knowledge_retention_guard('embedding,content_sha256','ordinary');
CREATE TRIGGER z_purge_visibility AFTER UPDATE OF purged_at ON knowledge_items FOR EACH ROW WHEN (OLD.purged_at IS DISTINCT FROM NEW.purged_at) EXECUTE FUNCTION cip_authz_changed();

CREATE FUNCTION cip_purge_knowledge(organization uuid,identity uuid,expected bigint,actor uuid,automatic boolean)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE k knowledge_items%ROWTYPE; prior_id text; prior_org text;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('cip:b1:'||organization::text,0));
 SELECT * INTO k FROM knowledge_items WHERE org_id=organization AND id=identity FOR UPDATE;
 IF NOT FOUND OR k.lock_version<>expected OR k.recycled_at IS NULL OR k.purged_at IS NOT NULL THEN RETURN false; END IF;
 IF automatic THEN
  IF k.recycled_at+interval '720 hours'>clock_timestamp() OR actor IS NOT NULL THEN RETURN false; END IF;
 ELSIF actor IS NULL OR NOT EXISTS(SELECT 1 FROM members WHERE org_id=organization AND id=actor AND disabled_at IS NULL) THEN RETURN false;
 END IF;
 prior_id:=current_setting('cip.purge_knowledge',true);prior_org:=current_setting('cip.purge_org',true);
 PERFORM set_config('cip.purge_knowledge',identity::text,true);PERFORM set_config('cip.purge_org',organization::text,true);
 UPDATE knowledge_items SET title='[已永久删除]',purged_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=organization AND id=identity;
 UPDATE knowledge_revisions SET title='[已永久删除]',body_text='[已永久删除]',tags='[]'::jsonb,limitations=NULL,source_text=NULL,explanation=NULL WHERE org_id=organization AND knowledge_id=identity;
 DELETE FROM embeddings WHERE org_id=organization AND search_document_id IN (SELECT d.id FROM search_documents d JOIN knowledge_publications p ON p.org_id=d.org_id AND p.id=d.publication_id WHERE p.org_id=organization AND p.knowledge_id=identity);
 DELETE FROM search_documents WHERE org_id=organization AND publication_id IN (SELECT id FROM knowledge_publications WHERE org_id=organization AND knowledge_id=identity);
 INSERT INTO audit_events(id,org_id,actor_member_id,action_code,target_kind,target_id,request_id,safe_details)
 VALUES(gen_random_uuid(),organization,actor,CASE WHEN automatic THEN 'knowledge.retention_purged' ELSE 'knowledge.purged' END,'knowledge',identity,gen_random_uuid()::text,jsonb_build_object('automatic',automatic,'recycled_at',k.recycled_at,'retention_hours',720));
 PERFORM set_config('cip.purge_knowledge',COALESCE(prior_id,''),true);PERFORM set_config('cip.purge_org',COALESCE(prior_org,''),true);
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION cip_purge_knowledge(uuid,uuid,bigint,uuid,boolean) FROM PUBLIC;
