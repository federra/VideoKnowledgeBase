DROP TRIGGER zz_submission_handoff ON research_submissions;
DROP FUNCTION cip_submission_handoff_guard();
ALTER TABLE research_submissions DROP CONSTRAINT fk_submission_handoff;
ALTER TABLE research_submissions DROP COLUMN handoff_id;
