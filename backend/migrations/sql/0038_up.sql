ALTER TABLE topic_sparks ADD COLUMN deleted_at timestamptz;
ALTER TABLE topic_spark_revisions ADD COLUMN color text NOT NULL DEFAULT 'violet'
    CONSTRAINT ck_topic_spark_revisions_color CHECK (color IN ('violet','teal','amber'));
DROP TRIGGER z_immutable ON topic_sparks;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_sparks
    FOR EACH ROW EXECUTE FUNCTION cip_immutable('current_revision_id,updated_at,lock_version,deleted_at','ordinary');
