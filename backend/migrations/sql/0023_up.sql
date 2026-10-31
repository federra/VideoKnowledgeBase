ALTER TABLE knowledge_items ADD COLUMN recycled_at timestamptz;
ALTER TABLE knowledge_items ADD COLUMN recycled_by uuid;
ALTER TABLE knowledge_items ADD CONSTRAINT ck_knowledge_recycle_pair CHECK ((recycled_at IS NULL)=(recycled_by IS NULL));
ALTER TABLE knowledge_items ADD CONSTRAINT fk_knowledge_recycled_member FOREIGN KEY(org_id,recycled_by) REFERENCES members(org_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
DROP TRIGGER z_immutable ON knowledge_items;
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON knowledge_items FOR EACH ROW EXECUTE FUNCTION cip_immutable('title,owner_member_id,current_revision_id,published_publication_id,recycled_at,recycled_by,updated_at,lock_version','ordinary');
CREATE TRIGGER z_recycle_visibility AFTER UPDATE OF recycled_at ON knowledge_items FOR EACH ROW WHEN (OLD.recycled_at IS DISTINCT FROM NEW.recycled_at) EXECUTE FUNCTION cip_authz_changed();
