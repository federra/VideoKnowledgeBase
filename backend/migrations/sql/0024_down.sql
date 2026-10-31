DO $$ BEGIN IF EXISTS (SELECT 1 FROM knowledge_revisions WHERE source_text IS NOT NULL OR explanation IS NOT NULL) THEN RAISE EXCEPTION 'knowledge attribution fields contain data; restore a consistent backup instead'; END IF; END $$;
ALTER TABLE knowledge_revisions DROP COLUMN source_text, DROP COLUMN explanation;
