
CREATE TABLE insight_reports (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	feedback_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	schema_version INTEGER DEFAULT 1 NOT NULL, 
	body JSONB NOT NULL, 
	CONSTRAINT pk_insight_reports PRIMARY KEY (id), 
	CONSTRAINT uq_insight_reports_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_insight_reports_0 CHECK (schema_version=1), 
	CONSTRAINT uq_insight_reports_0 UNIQUE (org_id, feedback_id, schema_version), 
	CONSTRAINT uq_insight_reports_1 UNIQUE (org_id, task_id), 
	CONSTRAINT ck_insight_reports_schema_version CHECK (schema_version > 0), 
	CONSTRAINT ck_insight_reports_body CHECK (jsonb_typeof(body) = 'object')
)

;

ALTER TABLE insight_reports ADD CONSTRAINT fk_insight_reports_0 FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE insight_reports ADD CONSTRAINT fk_insight_reports_1 FOREIGN KEY(org_id, feedback_id) REFERENCES feedback_snapshots (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE insight_reports ADD CONSTRAINT fk_insight_reports_2 FOREIGN KEY(org_id, task_id) REFERENCES tasks (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX ix_insight_reports_fk_0 ON insight_reports (org_id);
CREATE INDEX ix_insight_reports_fk_1 ON insight_reports (org_id, feedback_id);
CREATE INDEX ix_insight_reports_fk_2 ON insight_reports (org_id, task_id);
CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON insight_reports FOR EACH ROW EXECUTE FUNCTION cip_write_lock();
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON insight_reports FOR EACH ROW EXECUTE FUNCTION cip_immutable('','ordinary');
CREATE FUNCTION cip_insight_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM feedback_snapshots f JOIN intelligence_snapshots s ON s.id=f.snapshot_id AND s.org_id=f.org_id JOIN tasks t ON t.id=NEW.task_id AND t.org_id=NEW.org_id WHERE f.org_id=NEW.org_id AND f.id=NEW.feedback_id AND f.sealed_at IS NOT NULL AND t.state='succeeded' AND t.kind='intelligence.insight' AND t.max_external_calls=0 AND t.business_code=s.business_code AND (SELECT count(*) FROM task_inputs i WHERE i.org_id=NEW.org_id AND i.task_id=t.id)=1 AND EXISTS(SELECT 1 FROM task_inputs i WHERE i.org_id=NEW.org_id AND i.task_id=t.id AND i.feedback_id=f.id)) THEN RAISE EXCEPTION 'insight requires exact sealed feedback and zero-call successful task'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_insight AFTER INSERT ON insight_reports DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_insight_guard();
