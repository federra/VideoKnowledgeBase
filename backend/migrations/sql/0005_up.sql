-- S05.2 incremental service storage. Existing B1 snapshots are unchanged.

CREATE TABLE auth_sessions (
	id UUID NOT NULL, 
	org_id UUID NOT NULL, 
	member_id UUID NOT NULL, 
	token_hash CHAR(64) NOT NULL, 
	credential_hash CHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_auth_sessions PRIMARY KEY (id), 
	CONSTRAINT fk_auth_sessions_org_id_members FOREIGN KEY(org_id, member_id) REFERENCES members (org_id, id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CHECK (expires_at>created_at), 
	CHECK (token_hash ~ '^[0-9a-f]{64}$' AND credential_hash ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT uq_auth_sessions_token_hash UNIQUE (token_hash)
)

;
CREATE INDEX ix_auth_sessions_member ON auth_sessions (org_id, member_id);

CREATE TABLE auth_rate_limits (
	bucket CHAR(64) NOT NULL, 
	window_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	CONSTRAINT pk_auth_rate_limits PRIMARY KEY (bucket), 
	CHECK (attempts>0)
)

;

CREATE TABLE http_receipts (
	org_id UUID NOT NULL, 
	member_id UUID NOT NULL, 
	operation TEXT NOT NULL, 
	key UUID NOT NULL, 
	input_sha256 CHAR(64) NOT NULL, 
	response JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	CONSTRAINT pk_http_receipts PRIMARY KEY (org_id, member_id, operation, key), 
	CONSTRAINT fk_http_receipts_org_id_members FOREIGN KEY(org_id, member_id) REFERENCES members (org_id, id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CHECK (input_sha256 ~ '^[0-9a-f]{64}$' AND btrim(operation)<>''), 
	CHECK (jsonb_typeof(response)='object')
)

;

CREATE FUNCTION cip_auth_session_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable session history'; END IF;
 IF (to_jsonb(NEW)-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'revoked_at') OR
    OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL THEN
   RAISE EXCEPTION 'immutable session identity';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER a_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON auth_sessions FOR EACH ROW EXECUTE FUNCTION cip_write_lock();
CREATE TRIGGER z_auth_session BEFORE UPDATE OR DELETE ON auth_sessions FOR EACH ROW EXECUTE FUNCTION cip_auth_session_guard();
CREATE FUNCTION cip_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable receipt'; END $$;
CREATE TRIGGER a_tenant_lock BEFORE INSERT OR UPDATE OR DELETE ON http_receipts FOR EACH ROW EXECUTE FUNCTION cip_write_lock();
CREATE TRIGGER z_http_receipt BEFORE UPDATE OR DELETE ON http_receipts FOR EACH ROW EXECUTE FUNCTION cip_receipt_guard();
CREATE TRIGGER z_visibility_epoch AFTER INSERT OR UPDATE OR DELETE ON file_objects FOR EACH ROW EXECUTE FUNCTION cip_authz_changed();
CREATE TRIGGER z_visibility_epoch AFTER UPDATE OF published_publication_id ON knowledge_items FOR EACH ROW WHEN (OLD.published_publication_id IS DISTINCT FROM NEW.published_publication_id) EXECUTE FUNCTION cip_authz_changed();
CREATE TRIGGER z_visibility_epoch AFTER INSERT OR UPDATE OR DELETE ON knowledge_businesses FOR EACH ROW EXECUTE FUNCTION cip_authz_changed();
