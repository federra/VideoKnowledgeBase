ALTER TABLE research_submissions ADD COLUMN handoff_id uuid;
ALTER TABLE research_submissions ADD CONSTRAINT fk_submission_handoff FOREIGN KEY(org_id,handoff_id) REFERENCES intelligence_handoffs(org_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION cip_submission_handoff_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NEW.handoff_id IS NOT NULL AND (NEW.origin<>'intelligence' OR NOT EXISTS(
 SELECT 1 FROM intelligence_handoffs h WHERE h.org_id=NEW.org_id AND h.id=NEW.handoff_id AND h.snapshot_entry_id=NEW.snapshot_entry_id AND h.feedback_id IS NOT DISTINCT FROM NEW.feedback_id)) THEN RAISE EXCEPTION 'submission handoff must match exact source and feedback'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_submission_handoff AFTER INSERT ON research_submissions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_submission_handoff_guard();
REVOKE EXECUTE ON FUNCTION cip_submission_handoff_guard() FROM PUBLIC;
