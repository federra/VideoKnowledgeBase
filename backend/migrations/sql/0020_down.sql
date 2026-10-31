DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM knowledge_publications WHERE release_mode='legacy_import') THEN
  RAISE EXCEPTION 'Cannot downgrade while legacy imported publications exist; preserve imported evidence';
 END IF;
END $$;
DROP TRIGGER b_legacy_publication ON knowledge_publications;
DROP FUNCTION cip_legacy_publication_guard();
ALTER TABLE knowledge_publications DROP CONSTRAINT ck_publication_release_mode;
ALTER TABLE knowledge_publications DROP COLUMN import_metadata;
ALTER TABLE knowledge_publications DROP COLUMN release_mode;
ALTER TABLE knowledge_publications ALTER COLUMN review_request_id SET NOT NULL;
ALTER TABLE knowledge_publications ALTER COLUMN ai_decision_id SET NOT NULL;
ALTER TABLE knowledge_publications ALTER COLUMN human_decision_id SET NOT NULL;
