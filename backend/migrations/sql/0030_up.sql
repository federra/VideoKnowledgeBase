-- Additive topic inventory; no old constraints, grants or business facts are changed.

CREATE TABLE topic_cards (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	business_code TEXT NOT NULL, 
	status TEXT DEFAULT 'candidate' NOT NULL, 
	current_revision_id UUID NOT NULL, 
	selected_revision_id UUID, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_topic_cards PRIMARY KEY (id), 
	CONSTRAINT uq_topic_cards_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_topic_cards_0 CHECK (status IN ('candidate','production')), 
	CONSTRAINT ck_topic_cards_lock_version CHECK (lock_version > 0), 
	CONSTRAINT ck_topic_cards_business_code_nonempty CHECK (btrim(business_code)<>''), 
	CONSTRAINT ck_topic_cards_status_nonempty CHECK (btrim(status)<>'')
);

CREATE TABLE topic_revisions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	topic_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	fields JSONB NOT NULL, 
	origin TEXT NOT NULL, 
	source_refs JSONB NOT NULL, 
	generation_task_id UUID, 
	content_sha256 CHAR(64) NOT NULL, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_topic_revisions PRIMARY KEY (id), 
	CONSTRAINT uq_topic_revisions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_topic_revisions_0 CHECK (origin IN ('manual','batch','brainstorm')), 
	CONSTRAINT uq_topic_revisions_0 UNIQUE (org_id, topic_id, version_no), 
	CONSTRAINT uq_topic_revisions_1 UNIQUE (org_id, topic_id, id), 
	CONSTRAINT ck_topic_revisions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_topic_revisions_fields CHECK (jsonb_typeof(fields) = 'object'), 
	CONSTRAINT ck_topic_revisions_origin_nonempty CHECK (btrim(origin)<>''), 
	CONSTRAINT ck_topic_revisions_source_refs CHECK (jsonb_typeof(source_refs) = 'object'), 
	CONSTRAINT ck_topic_revisions_content_sha256 CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE topic_sparks (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	lock_version BIGINT DEFAULT 1 NOT NULL, 
	owner_member_id UUID NOT NULL, 
	current_revision_id UUID NOT NULL, 
	CONSTRAINT pk_topic_sparks PRIMARY KEY (id), 
	CONSTRAINT uq_topic_sparks_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_topic_sparks_lock_version CHECK (lock_version > 0)
);

CREATE TABLE topic_spark_revisions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	spark_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	title TEXT NOT NULL, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_topic_spark_revisions PRIMARY KEY (id), 
	CONSTRAINT uq_topic_spark_revisions_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT uq_topic_spark_revisions_0 UNIQUE (org_id, spark_id, version_no), 
	CONSTRAINT uq_topic_spark_revisions_1 UNIQUE (org_id, spark_id, id), 
	CONSTRAINT ck_topic_spark_revisions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_topic_spark_revisions_text_nonempty CHECK (btrim(text)<>''), 
	CONSTRAINT ck_topic_spark_revisions_title_nonempty CHECK (btrim(title)<>'')
);

CREATE TABLE topic_saved_generations (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	task_id UUID NOT NULL, 
	topic_id UUID NOT NULL, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_topic_saved_generations PRIMARY KEY (id), 
	CONSTRAINT uq_topic_saved_generations_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT uq_topic_saved_generations_0 UNIQUE (org_id, task_id)
);

CREATE TABLE topic_handoffs (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	topic_id UUID NOT NULL, 
	topic_revision_id UUID NOT NULL, 
	method TEXT NOT NULL, 
	created_by UUID NOT NULL, 
	CONSTRAINT pk_topic_handoffs PRIMARY KEY (id), 
	CONSTRAINT uq_topic_handoffs_tenant_id UNIQUE (org_id, id), 
	CONSTRAINT ck_topic_handoffs_0 CHECK (method IN ('copy','export')), 
	CONSTRAINT ck_topic_handoffs_method_nonempty CHECK (btrim(method)<>'')
);

ALTER TABLE topic_cards ADD CONSTRAINT fk_topic_cards_business_code FOREIGN KEY(business_code) REFERENCES business_lines (code) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_cards ADD CONSTRAINT fk_topic_cards_created_by FOREIGN KEY(org_id, created_by) REFERENCES members (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_cards ADD CONSTRAINT fk_topic_cards_id_current_revision_id FOREIGN KEY(org_id, id, current_revision_id) REFERENCES topic_revisions (org_id, topic_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_cards ADD CONSTRAINT fk_topic_cards_id_selected_revision_id FOREIGN KEY(org_id, id, selected_revision_id) REFERENCES topic_revisions (org_id, topic_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_cards ADD CONSTRAINT fk_topic_cards_organization FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX ix_topic_cards_org_id_business_code_status_created_at ON topic_cards (org_id, business_code, status, created_at);

CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON topic_cards FOR EACH ROW EXECUTE FUNCTION cip_write_lock();

CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_cards FOR EACH ROW EXECUTE FUNCTION cip_immutable('status,current_revision_id,selected_revision_id,updated_at,lock_version','ordinary');

ALTER TABLE topic_revisions ADD CONSTRAINT fk_topic_revisions_created_by FOREIGN KEY(org_id, created_by) REFERENCES members (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_revisions ADD CONSTRAINT fk_topic_revisions_generation_task_id FOREIGN KEY(org_id, generation_task_id) REFERENCES tasks (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_revisions ADD CONSTRAINT fk_topic_revisions_organization FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_revisions ADD CONSTRAINT fk_topic_revisions_topic_id FOREIGN KEY(org_id, topic_id) REFERENCES topic_cards (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON topic_revisions FOR EACH ROW EXECUTE FUNCTION cip_write_lock();

CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_revisions FOR EACH ROW EXECUTE FUNCTION cip_immutable('','ordinary');

ALTER TABLE topic_sparks ADD CONSTRAINT fk_topic_sparks_id_current_revision_id FOREIGN KEY(org_id, id, current_revision_id) REFERENCES topic_spark_revisions (org_id, spark_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_sparks ADD CONSTRAINT fk_topic_sparks_organization FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_sparks ADD CONSTRAINT fk_topic_sparks_owner_member_id FOREIGN KEY(org_id, owner_member_id) REFERENCES members (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX ix_topic_sparks_org_id_owner_member_id_created_at ON topic_sparks (org_id, owner_member_id, created_at);

CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON topic_sparks FOR EACH ROW EXECUTE FUNCTION cip_write_lock();

CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_sparks FOR EACH ROW EXECUTE FUNCTION cip_immutable('current_revision_id,updated_at,lock_version','ordinary');

ALTER TABLE topic_spark_revisions ADD CONSTRAINT fk_topic_spark_revisions_created_by FOREIGN KEY(org_id, created_by) REFERENCES members (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_spark_revisions ADD CONSTRAINT fk_topic_spark_revisions_organization FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_spark_revisions ADD CONSTRAINT fk_topic_spark_revisions_spark_id FOREIGN KEY(org_id, spark_id) REFERENCES topic_sparks (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON topic_spark_revisions FOR EACH ROW EXECUTE FUNCTION cip_write_lock();

CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_spark_revisions FOR EACH ROW EXECUTE FUNCTION cip_immutable('','ordinary');

ALTER TABLE topic_saved_generations ADD CONSTRAINT fk_topic_saved_generations_created_by FOREIGN KEY(org_id, created_by) REFERENCES members (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_saved_generations ADD CONSTRAINT fk_topic_saved_generations_organization FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_saved_generations ADD CONSTRAINT fk_topic_saved_generations_task_id FOREIGN KEY(org_id, task_id) REFERENCES tasks (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_saved_generations ADD CONSTRAINT fk_topic_saved_generations_topic_id FOREIGN KEY(org_id, topic_id) REFERENCES topic_cards (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON topic_saved_generations FOR EACH ROW EXECUTE FUNCTION cip_write_lock();

CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_saved_generations FOR EACH ROW EXECUTE FUNCTION cip_immutable('','ordinary');

ALTER TABLE topic_handoffs ADD CONSTRAINT fk_topic_handoffs_created_by FOREIGN KEY(org_id, created_by) REFERENCES members (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_handoffs ADD CONSTRAINT fk_topic_handoffs_organization FOREIGN KEY(org_id) REFERENCES organizations (id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_handoffs ADD CONSTRAINT fk_topic_handoffs_topic_id FOREIGN KEY(org_id, topic_id) REFERENCES topic_cards (org_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE topic_handoffs ADD CONSTRAINT fk_topic_handoffs_topic_id_topic_revision_id FOREIGN KEY(org_id, topic_id, topic_revision_id) REFERENCES topic_revisions (org_id, topic_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX ix_topic_handoffs_org_id_topic_id_created_at ON topic_handoffs (org_id, topic_id, created_at);

CREATE TRIGGER a0_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON topic_handoffs FOR EACH ROW EXECUTE FUNCTION cip_write_lock();

CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON topic_handoffs FOR EACH ROW EXECUTE FUNCTION cip_immutable('','ordinary');

CREATE FUNCTION cip_topic_revision_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE prior integer; owner_id uuid;
BEGIN
 IF TG_TABLE_NAME='topic_revisions' THEN
   SELECT coalesce(max(version_no),0) INTO prior FROM topic_revisions
     WHERE org_id=NEW.org_id AND topic_id=NEW.topic_id;
 ELSE
   SELECT owner_member_id INTO owner_id FROM topic_sparks
     WHERE org_id=NEW.org_id AND id=NEW.spark_id;
   IF owner_id IS DISTINCT FROM NEW.created_by THEN
     RAISE EXCEPTION 'spark revision requires owner';
   END IF;
   SELECT coalesce(max(version_no),0) INTO prior FROM topic_spark_revisions
     WHERE org_id=NEW.org_id AND spark_id=NEW.spark_id;
 END IF;
 IF NEW.version_no<>prior+1 THEN
   RAISE EXCEPTION 'VERSION_CONFLICT: revision must advance once';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER b_topic_revision BEFORE INSERT ON topic_revisions
 FOR EACH ROW EXECUTE FUNCTION cip_topic_revision_guard();
CREATE TRIGGER b_topic_revision BEFORE INSERT ON topic_spark_revisions
 FOR EACH ROW EXECUTE FUNCTION cip_topic_revision_guard();
