DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM topic_sparks WHERE deleted_at IS NOT NULL)
       OR EXISTS (SELECT 1 FROM topic_spark_revisions WHERE color <> 'violet') THEN
        RAISE EXCEPTION 'Cannot downgrade with deleted or recolored sparks';
    END IF;
END $$;
DROP TRIGGER z_immutable ON topic_sparks;
ALTER TABLE topic_sparks DROP COLUMN deleted_at;
ALTER TABLE topic_spark_revisions DROP COLUMN color;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_sparks
    FOR EACH ROW EXECUTE FUNCTION cip_immutable('current_revision_id,updated_at,lock_version','ordinary');
