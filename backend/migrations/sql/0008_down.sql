DROP TRIGGER z_immutable ON sources;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON sources FOR EACH ROW EXECUTE FUNCTION cip_immutable('name,enabled,updated_at,lock_version','ordinary');
ALTER TABLE sources DROP CONSTRAINT ck_sources_archived_paused;
ALTER TABLE sources DROP COLUMN archived_at;
