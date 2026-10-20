
CREATE TABLE intelligence_handoffs (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	snapshot_id UUID NOT NULL, 
	snapshot_entry_id UUID NOT NULL, 
	content_observation_id UUID NOT NULL, 
	feedback_id UUID, 
	business_code TEXT NOT NULL, 
	business_date DATE NOT NULL, 
	frozen_by UUID NOT NULL, 
	idempotency_key TEXT NOT NULL, 
	schema_version INTEGER DEFAULT 1 NOT NULL, 
	manifest_sha256 CHAR(64) NOT NULL, 
	body JSONB NOT NULL, 
	CONSTRAINT pk_intelligence_handoffs PRIMARY KEY (id), 
	CONSTRAINT uq_intelligence_handoffs_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_intelligence_handoffs_0 CHECK (schema_version=1), 
	CONSTRAINT ck_intelligence_handoffs_1 CHECK (btrim(idempotency_key)<>''), 
	CONSTRAINT uq_intelligence_handoffs_0 UNIQUE (org_id, frozen_by, idempotency_key), 
	CONSTRAINT ck_intelligence_handoffs_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_intelligence_handoffs_idempotency_key_nonempty CHECK (btrim(idempotency_key)<>''), 
	CONSTRAINT ck_intelligence_handoffs_schema_version CHECK (schema_version > 0), 
	CONSTRAINT ck_intelligence_handoffs_manifest_sha256 CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT ck_intelligence_handoffs_body CHECK (jsonb_typeof(body) = 'object')
)

;
ALTER TABLE intelligence_handoffs ADD CONSTRAINT fk_intelligence_handoffs_0 FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE intelligence_handoffs ADD CONSTRAINT fk_intelligence_handoffs_1 FOREIGN KEY(org_id, snapshot_id) REFERENCES intelligence_snapshots (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE intelligence_handoffs ADD CONSTRAINT fk_intelligence_handoffs_2 FOREIGN KEY(org_id, snapshot_entry_id) REFERENCES snapshot_entries (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE intelligence_handoffs ADD CONSTRAINT fk_intelligence_handoffs_3 FOREIGN KEY(org_id, content_observation_id) REFERENCES content_observations (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE intelligence_handoffs ADD CONSTRAINT fk_intelligence_handoffs_4 FOREIGN KEY(org_id, feedback_id) REFERENCES feedback_snapshots (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE intelligence_handoffs ADD CONSTRAINT fk_intelligence_handoffs_5 FOREIGN KEY(business_code) REFERENCES business_lines (code) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE intelligence_handoffs ADD CONSTRAINT fk_intelligence_handoffs_6 FOREIGN KEY(org_id, frozen_by) REFERENCES members (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX ix_intelligence_handoffs_fk_0 ON intelligence_handoffs (org_id);
CREATE INDEX ix_intelligence_handoffs_fk_1 ON intelligence_handoffs (org_id, snapshot_id);
CREATE INDEX ix_intelligence_handoffs_fk_2 ON intelligence_handoffs (org_id, snapshot_entry_id);
CREATE INDEX ix_intelligence_handoffs_fk_3 ON intelligence_handoffs (org_id, content_observation_id);
CREATE INDEX ix_intelligence_handoffs_fk_4 ON intelligence_handoffs (org_id, feedback_id);
CREATE INDEX ix_intelligence_handoffs_fk_5 ON intelligence_handoffs (business_code);
CREATE INDEX ix_intelligence_handoffs_fk_6 ON intelligence_handoffs (org_id, frozen_by);

CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON intelligence_handoffs FOR EACH ROW EXECUTE FUNCTION cip_write_lock();
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON intelligence_handoffs FOR EACH ROW EXECUTE FUNCTION cip_immutable('','ordinary');
CREATE FUNCTION cip_handoff_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM snapshot_entries e JOIN intelligence_snapshots s ON s.id=e.snapshot_id AND s.org_id=e.org_id WHERE e.org_id=NEW.org_id AND e.id=NEW.snapshot_entry_id AND s.id=NEW.snapshot_id AND s.sealed_at IS NOT NULL AND e.content_observation_id=NEW.content_observation_id AND s.business_code=NEW.business_code AND s.business_date=NEW.business_date) THEN RAISE EXCEPTION 'handoff requires exact sealed snapshot entry'; END IF;
 IF NEW.feedback_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM feedback_snapshots f WHERE f.org_id=NEW.org_id AND f.id=NEW.feedback_id AND f.snapshot_id=NEW.snapshot_id AND f.sealed_at IS NOT NULL) THEN RAISE EXCEPTION 'handoff feedback must be sealed on same snapshot'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_handoff AFTER INSERT ON intelligence_handoffs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_handoff_guard();
