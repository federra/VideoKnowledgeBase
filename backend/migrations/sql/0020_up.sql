ALTER TABLE knowledge_publications ALTER COLUMN review_request_id DROP NOT NULL;
ALTER TABLE knowledge_publications ALTER COLUMN ai_decision_id DROP NOT NULL;
ALTER TABLE knowledge_publications ALTER COLUMN human_decision_id DROP NOT NULL;
ALTER TABLE knowledge_publications ADD COLUMN release_mode text NOT NULL DEFAULT 'double_review';
ALTER TABLE knowledge_publications ADD COLUMN import_metadata jsonb;
ALTER TABLE knowledge_publications ADD CONSTRAINT ck_publication_release_mode CHECK (
 (release_mode='double_review' AND review_request_id IS NOT NULL AND ai_decision_id IS NOT NULL AND human_decision_id IS NOT NULL AND import_metadata IS NULL)
 OR (release_mode='legacy_import' AND review_request_id IS NULL AND ai_decision_id IS NULL AND human_decision_id IS NULL AND import_metadata IS NOT NULL
 AND jsonb_typeof(import_metadata)='object'
 AND COALESCE(import_metadata->>'source_sha256','') ~ '^[a-f0-9]{64}$'
 AND btrim(COALESCE(import_metadata->>'reason',''))<>''
 AND btrim(COALESCE(import_metadata->>'source_name',''))<>''
 AND btrim(COALESCE(import_metadata->>'source_code',''))<>''
 AND COALESCE(jsonb_typeof(import_metadata->'locations'),'')='array')
);
CREATE FUNCTION cip_legacy_publication_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NEW.release_mode='legacy_import' THEN
  IF current_user<>(SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='knowledge_publications') THEN
   RAISE EXCEPTION 'legacy import requires local database owner'; END IF;
  IF NOT EXISTS(SELECT 1 FROM knowledge_revisions v WHERE v.org_id=NEW.org_id AND v.id=NEW.revision_id
   AND v.version_no=1 AND v.origin='manual' AND v.browse_category IN ('quote','genre') AND v.sealed_at IS NOT NULL)
   OR EXISTS(SELECT 1 FROM knowledge_publications WHERE org_id=NEW.org_id AND knowledge_id=NEW.knowledge_id)
   OR NOT EXISTS(SELECT 1 FROM knowledge_evidence e JOIN evidence_refs r ON r.org_id=e.org_id AND r.id=e.evidence_id
      JOIN raw_assets a ON a.org_id=r.org_id AND a.id=r.raw_asset_id
      WHERE e.org_id=NEW.org_id AND e.revision_id=NEW.revision_id AND a.origin='manual' AND length(r.quoted_text)>0)
   THEN RAISE EXCEPTION 'legacy import requires original first revision and manual evidence'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER b_legacy_publication BEFORE INSERT ON knowledge_publications FOR EACH ROW EXECUTE FUNCTION cip_legacy_publication_guard();
