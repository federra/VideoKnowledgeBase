-- S05.4 bounded runtime operations. Application cannot update state or Attempts directly.
CREATE FUNCTION cip_task_control(organization uuid, identity uuid, expected_version bigint,
 operation text, attempt uuid DEFAULT NULL, token uuid DEFAULT NULL,
 seconds integer DEFAULT 0, error_code text DEFAULT NULL)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE t tasks; a task_attempts; result_state text; code text; calls bigint;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('cip:b1:'||organization::text,0));
 SELECT * INTO t FROM tasks WHERE org_id=organization AND id=identity FOR UPDATE;
 IF t.id IS NULL OR t.lock_version<>expected_version THEN RETURN false; END IF;
 SELECT * INTO a FROM task_attempts WHERE org_id=organization AND task_id=t.id
  AND finished_at IS NULL FOR UPDATE;
 SELECT (SELECT count(*) FROM collection_calls cc JOIN collection_jobs j ON j.id=cc.job_id WHERE j.task_id=t.id)
   +(SELECT count(*) FROM ai_executions WHERE task_id=t.id) INTO calls;
 IF operation='renew' THEN
  IF seconds NOT BETWEEN 1 AND 3600 THEN RAISE EXCEPTION 'invalid lease'; END IF;
  IF t.state<>'running' OR a.id IS DISTINCT FROM attempt OR a.worker_token IS DISTINCT FROM token
    OR a.lease_expires_at<=clock_timestamp() THEN RETURN false; END IF;
  UPDATE task_attempts SET lease_expires_at=clock_timestamp()+make_interval(secs=>seconds) WHERE id=a.id;
  RETURN true;
 ELSIF operation='fail_queued' THEN
  IF t.state<>'queued' OR a.id IS NOT NULL THEN RETURN false; END IF;
  IF error_code NOT IN ('INVALID_INPUT','ACCESS_REVOKED','HANDLER_UNAVAILABLE') OR error_code IS NULL
   THEN RAISE EXCEPTION 'invalid preflight error'; END IF;
  UPDATE tasks SET state='failed',safe_error_code=error_code,finished_at=clock_timestamp(),
   lock_version=lock_version+1 WHERE id=t.id;
 ELSIF operation='cancel' THEN
  IF t.state NOT IN ('queued','running') THEN RETURN false; END IF;
  UPDATE tasks SET state=CASE WHEN t.state='queued' THEN 'cancelled' ELSE 'cancel_requested' END,
   finished_at=CASE WHEN t.state='queued' THEN clock_timestamp() ELSE NULL END,
   cancel_requested_at=clock_timestamp(),lock_version=lock_version+1 WHERE id=t.id;
 ELSIF operation='recover' THEN
  IF t.state NOT IN ('running','cancel_requested') OR a.id IS NULL
    OR a.lease_expires_at>clock_timestamp() THEN RETURN false; END IF;
  result_state:=CASE WHEN t.state='cancel_requested' AND calls=0 THEN 'cancelled' ELSE 'failed' END;
  code:=CASE WHEN calls>0 THEN 'EXTERNAL_RESULT_UNKNOWN' WHEN result_state='failed' THEN 'LEASE_LOST' ELSE NULL END;
  UPDATE task_attempts SET outcome=CASE WHEN result_state='cancelled' THEN 'cancelled' ELSE 'lease_lost' END,
   finished_at=clock_timestamp(),safe_error_code=code WHERE id=a.id;
  UPDATE tasks SET state=result_state,finished_at=clock_timestamp(),safe_error_code=code,
   lock_version=lock_version+1 WHERE id=t.id;
 ELSIF operation='retry' THEN
  IF seconds NOT BETWEEN 1 AND 300 THEN RAISE EXCEPTION 'invalid backoff'; END IF;
  IF t.state<>'failed' OR a.id IS NOT NULL OR calls>0 OR t.safe_error_code IS NULL OR
     t.safe_error_code NOT IN ('LOCAL_TRANSIENT','LEASE_LOST','TIMEOUT') OR
     (SELECT count(*) FROM task_attempts WHERE task_id=t.id)>=t.max_attempts THEN RETURN false; END IF;
  UPDATE tasks SET state='queued',finished_at=NULL,safe_error_code=NULL,
   available_at=clock_timestamp()+make_interval(secs=>seconds),lock_version=lock_version+1 WHERE id=t.id;
 ELSE RAISE EXCEPTION 'unsupported task control';
 END IF;
 UPDATE analysis_runs SET state=(SELECT state FROM tasks WHERE id=t.id),
  finished_at=(SELECT finished_at FROM tasks WHERE id=t.id),
  safe_error_code=(SELECT safe_error_code FROM tasks WHERE id=t.id) WHERE task_id=t.id;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION cip_task_control(uuid,uuid,bigint,text,uuid,uuid,integer,text) FROM PUBLIC;
