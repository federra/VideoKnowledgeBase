-- A database-wide singleton prevents simultaneous or repeated anonymous setup.
CREATE TABLE account_installations (
 id SMALLINT PRIMARY KEY CHECK (id=1),
 org_id UUID NOT NULL,
 owner_member_id UUID NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CONSTRAINT fk_account_installations_owner FOREIGN KEY (org_id,owner_member_id)
 REFERENCES members(org_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE TRIGGER z_immutable BEFORE UPDATE OR DELETE ON account_installations
 FOR EACH ROW EXECUTE FUNCTION cip_immutable('','ordinary');
-- Existing restricted application logins gain only the two operations needed.
DO $$ DECLARE r RECORD; BEGIN
 FOR r IN SELECT rolname FROM pg_roles WHERE rolname ~ '^cip_local_app_[a-f0-9]+$'
 LOOP
   EXECUTE format('GRANT SELECT, INSERT ON account_installations TO %I',r.rolname);
 END LOOP;
END $$;
