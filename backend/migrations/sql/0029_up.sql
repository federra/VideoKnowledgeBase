
CREATE TABLE model_sources (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	name TEXT NOT NULL, 
	capability TEXT NOT NULL, 
	connection_id UUID NOT NULL, 
	config_revision_id UUID NOT NULL, 
	enabled BOOLEAN DEFAULT false NOT NULL, 
	CONSTRAINT pk_model_sources PRIMARY KEY (id), 
	CONSTRAINT uq_model_sources_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_model_sources_0 CHECK (capability IN ('text','vision')), 
	CONSTRAINT uq_model_sources_0 UNIQUE (org_id, name), 
	CONSTRAINT ck_model_sources_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_model_sources_name_nonempty CHECK (btrim(name)<>''), 
	CONSTRAINT ck_model_sources_capability_nonempty CHECK (btrim(capability)<>'')
)

;
ALTER TABLE model_sources ADD CONSTRAINT fk_model_sources_0 FOREIGN KEY(org_id, connection_id) REFERENCES provider_connections (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE model_sources ADD CONSTRAINT fk_model_sources_1 FOREIGN KEY(org_id, config_revision_id) REFERENCES ai_config_revisions (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE model_sources ADD CONSTRAINT fk_model_sources_2 FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON model_sources FOR EACH ROW EXECUTE FUNCTION cip_write_lock();
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON model_sources FOR EACH ROW EXECUTE FUNCTION cip_immutable('name,capability,connection_id,config_revision_id,enabled,updated_at,lock_version','ordinary');

CREATE TABLE model_bindings (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	business_code TEXT NOT NULL, 
	bindings JSONB NOT NULL, 
	CONSTRAINT pk_model_bindings PRIMARY KEY (id), 
	CONSTRAINT uq_model_bindings_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_model_bindings_0 CHECK (business_code IN ('motion_comic','story_short','ecommerce_video')), 
	CONSTRAINT uq_model_bindings_0 UNIQUE (org_id, business_code), 
	CONSTRAINT ck_model_bindings_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_model_bindings_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_model_bindings_bindings CHECK (jsonb_typeof(bindings) = 'object')
)

;
ALTER TABLE model_bindings ADD CONSTRAINT fk_model_bindings_0 FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON model_bindings FOR EACH ROW EXECUTE FUNCTION cip_write_lock();
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON model_bindings FOR EACH ROW EXECUTE FUNCTION cip_immutable('bindings,updated_at,lock_version','ordinary');
-- Bindings must point at real sources within the same organization and capability.
CREATE FUNCTION cip_model_head_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE entry record; expected text;
BEGIN
 IF TG_TABLE_NAME='model_sources' THEN
   IF NOT EXISTS (SELECT 1 FROM ai_config_revisions r WHERE r.org_id=NEW.org_id AND r.id=NEW.config_revision_id AND r.provider_connection_id=NEW.connection_id AND r.parameters->>'capability'=NEW.capability) THEN
     RAISE EXCEPTION 'model revision connection or capability mismatch';
   END IF;
   IF EXISTS (SELECT 1 FROM model_bindings b CROSS JOIN LATERAL jsonb_each_text(b.bindings) e WHERE b.org_id=NEW.org_id AND e.value=NEW.id::text AND (CASE WHEN e.key IN ('visual','image') THEN 'vision' ELSE 'text' END)<>NEW.capability) THEN
     RAISE EXCEPTION 'bound model source capability cannot change';
   END IF;
 ELSE
   FOR entry IN SELECT key,value FROM jsonb_each_text(NEW.bindings) LOOP
     expected := CASE WHEN entry.key IN ('visual','image') THEN 'vision' WHEN entry.key IN ('decompose','report','feedback','insight','topic','topic_score','evaluate','predict','extract','review','retrospect') THEN 'text' ELSE NULL END;
     IF expected IS NULL OR NOT EXISTS (SELECT 1 FROM model_sources s WHERE s.org_id=NEW.org_id AND s.id=entry.value::uuid AND s.capability=expected) THEN
       RAISE EXCEPTION 'invalid model binding';
     END IF;
   END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER z_model_head_guard AFTER INSERT OR UPDATE ON model_sources DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_model_head_guard();
CREATE CONSTRAINT TRIGGER z_model_head_guard AFTER INSERT OR UPDATE ON model_bindings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_model_head_guard();
