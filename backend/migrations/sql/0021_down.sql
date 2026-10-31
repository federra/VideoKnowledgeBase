DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM knowledge_publications p JOIN knowledge_revisions r ON r.org_id=p.org_id AND r.id=p.revision_id WHERE p.release_mode='legacy_import' AND r.browse_category='failure') THEN
 RAISE EXCEPTION 'Cannot downgrade while legacy failure publications exist; preserve evidence';
 END IF;
END $$;
CREATE OR REPLACE FUNCTION cip_legacy_publication_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
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
