SQL = r"""
CREATE FUNCTION cip_finish_task(organization uuid,identity uuid,attempt uuid,token uuid,
 expected_version bigint,outcome text,business text DEFAULT NULL,error_code text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE t tasks; a task_attempts;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('cip:b1:'||organization::text,0));
 SELECT * INTO t FROM tasks WHERE org_id=organization AND id=identity FOR UPDATE;
 SELECT * INTO a FROM task_attempts WHERE org_id=organization AND id=attempt FOR UPDATE;
 IF t.id IS NULL OR a.id IS NULL OR a.task_id<>t.id OR a.worker_token<>token OR
    a.finished_at IS NOT NULL OR a.lease_expires_at<=clock_timestamp() OR t.lock_version<>expected_version OR
    (outcome='succeeded' AND t.state<>'running') OR
    (outcome='cancelled' AND t.state<>'cancel_requested') OR
    (outcome='failed' AND t.state NOT IN ('running','cancel_requested')) THEN
   RAISE EXCEPTION 'STALE_RESULT: token, state, version or lease mismatch'; END IF;
 IF outcome NOT IN ('succeeded','failed','cancelled') THEN RAISE EXCEPTION 'invalid outcome'; END IF;
 UPDATE task_attempts SET finished_at=clock_timestamp(),outcome=cip_finish_task.outcome,
    safe_error_code=error_code WHERE id=a.id;
 UPDATE tasks SET state=outcome,business_outcome=business,finished_at=clock_timestamp(),safe_error_code=error_code,
    outputs_sealed_at=CASE WHEN outcome='succeeded' THEN clock_timestamp() ELSE NULL END,
    lock_version=lock_version+1 WHERE id=t.id;
 UPDATE analysis_runs SET state=outcome,started_at=t.started_at,finished_at=(SELECT finished_at FROM tasks WHERE id=t.id),
    safe_error_code=error_code WHERE task_id=t.id;
END $$;
"""

CLAIM_SQL = r"""
CREATE FUNCTION cip_claim_task(organization uuid,identity uuid,expected_version bigint,lease_seconds integer)
RETURNS TABLE(attempt_id uuid,worker_token uuid,lock_version bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE t tasks; aid uuid:=gen_random_uuid(); tok uuid:=gen_random_uuid(); seq integer;
BEGIN
 IF lease_seconds<1 OR lease_seconds>3600 THEN RAISE EXCEPTION 'invalid lease interval'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('cip:b1:'||organization::text,0));
 SELECT * INTO t FROM tasks WHERE org_id=organization AND id=identity FOR UPDATE;
 IF t.id IS NULL OR t.state<>'queued' OR t.lock_version<>expected_version OR t.available_at>clock_timestamp() THEN
   RAISE EXCEPTION 'VERSION_CONFLICT: task unavailable'; END IF;
 SELECT count(*)+1 INTO seq FROM task_attempts a WHERE a.task_id=t.id;
 UPDATE tasks SET state='running',lock_version=tasks.lock_version+1 WHERE id=t.id;
 INSERT INTO task_attempts(id,org_id,task_id,attempt_no,worker_token,lease_expires_at)
  VALUES (aid,organization,identity,seq,tok,clock_timestamp()+make_interval(secs=>lease_seconds));
 UPDATE analysis_runs SET state='running',started_at=(SELECT started_at FROM tasks WHERE id=t.id),finished_at=NULL,safe_error_code=NULL WHERE task_id=t.id;
 RETURN QUERY SELECT aid,tok,t.lock_version+1;
END $$;
"""
SQL = (
    SQL.replace(
        "RETURNS void LANGUAGE plpgsql SET", "RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET"
    )
    + CLAIM_SQL
)
