-- S06.2 creator removal is archival; historical sources and evidence remain addressable.
ALTER TABLE sources ADD COLUMN archived_at timestamptz;
ALTER TABLE sources ADD CONSTRAINT ck_sources_archived_paused CHECK (archived_at IS NULL OR NOT enabled);
DROP TRIGGER z_immutable ON sources;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON sources FOR EACH ROW EXECUTE FUNCTION cip_immutable('name,enabled,archived_at,updated_at,lock_version','ordinary');
