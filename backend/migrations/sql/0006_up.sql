
CREATE TABLE file_intakes (
	org_id UUID NOT NULL, 
	file_id UUID NOT NULL, 
	work_id UUID NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	origin_kind TEXT NOT NULL, 
	source_url TEXT, 
	CONSTRAINT pk_file_intakes PRIMARY KEY (org_id, file_id), 
	CONSTRAINT fk_file_intakes_org_id_file_objects FOREIGN KEY(org_id, file_id) REFERENCES file_objects (org_id, id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CONSTRAINT fk_file_intakes_org_id_works FOREIGN KEY(org_id, work_id) REFERENCES works (org_id, id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CONSTRAINT fk_file_intakes_org_id_members FOREIGN KEY(org_id, created_by) REFERENCES members (org_id, id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CHECK (origin_kind IN ('upload','external')), 
	CHECK ((origin_kind='external')=(source_url IS NOT NULL))
)

;
CREATE INDEX ix_file_intakes_work ON file_intakes (org_id, work_id);
CREATE TRIGGER a_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON file_intakes FOR EACH ROW EXECUTE FUNCTION cip_write_lock();
CREATE TRIGGER z_file_intake_immutable BEFORE UPDATE OR DELETE ON file_intakes FOR EACH ROW EXECUTE FUNCTION cip_receipt_guard();
CREATE TRIGGER z_visibility_epoch AFTER INSERT ON file_intakes FOR EACH ROW EXECUTE FUNCTION cip_authz_changed();
CREATE FUNCTION cip_file_scope_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM artifact_versions v JOIN file_intakes i ON i.org_id=v.org_id AND i.file_id=v.file_id
     WHERE v.org_id=NEW.org_id AND v.work_id<>i.work_id) THEN
    RAISE EXCEPTION 'file intake work mismatch';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER z_file_scope AFTER INSERT OR UPDATE ON artifact_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_file_scope_guard();
CREATE CONSTRAINT TRIGGER z_file_scope AFTER INSERT ON file_intakes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_file_scope_guard();
