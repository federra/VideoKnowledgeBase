-- Never silently discard a live recycling state during downgrade.
DO $$ BEGIN IF EXISTS(SELECT 1 FROM knowledge_items WHERE recycled_at IS NOT NULL) THEN RAISE EXCEPTION 'restore recycled knowledge before downgrade'; END IF; END $$;
DROP TRIGGER z_recycle_visibility ON knowledge_items;
DROP TRIGGER z_immutable ON knowledge_items;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON knowledge_items FOR EACH ROW EXECUTE FUNCTION cip_immutable('title,owner_member_id,current_revision_id,published_publication_id,updated_at,lock_version','ordinary');
ALTER TABLE knowledge_items DROP CONSTRAINT fk_knowledge_recycled_member;
ALTER TABLE knowledge_items DROP CONSTRAINT ck_knowledge_recycle_pair;
ALTER TABLE knowledge_items DROP COLUMN recycled_by;
ALTER TABLE knowledge_items DROP COLUMN recycled_at;
