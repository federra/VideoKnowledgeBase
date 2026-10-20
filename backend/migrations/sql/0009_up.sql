CREATE OR REPLACE FUNCTION cip_runtime_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE t tasks; j collection_jobs; a task_attempts; n bigint; request_id uuid;
BEGIN
 IF TG_TABLE_NAME='task_attempts' THEN
   SELECT * INTO t FROM tasks WHERE id=NEW.task_id FOR UPDATE;
   IF TG_OP='INSERT' THEN
     IF t.state<>'running' OR NEW.attempt_no<>(SELECT count(*)+1 FROM task_attempts WHERE task_id=t.id)
       OR NEW.attempt_no>t.max_attempts THEN RAISE EXCEPTION 'invalid attempt state or budget'; END IF;
   ELSIF OLD.finished_at IS NOT NULL THEN RAISE EXCEPTION 'finished attempt immutable';
   ELSIF NEW.lease_expires_at<>OLD.lease_expires_at AND OLD.lease_expires_at<=clock_timestamp() THEN
      RAISE EXCEPTION 'lease lost';
   END IF;
 ELSIF TG_TABLE_NAME IN ('collection_calls','ai_executions') THEN
   IF TG_TABLE_NAME='collection_calls' THEN
     SELECT * INTO j FROM collection_jobs WHERE id=NEW.job_id;
     request_id:=j.task_id;
   ELSE request_id:=NEW.task_id;
   END IF;
   SELECT * INTO t FROM tasks WHERE id=request_id FOR UPDATE;
   -- cip_write_lock already holds the tenant mutex before this guard, and
   -- all attempt writes acquire the same mutex. A plain read preserves the
   -- lease/attempt fence without requiring UPDATE rights merely to read a row.
   SELECT * INTO a FROM task_attempts WHERE id=NEW.attempt_id;
   IF a.task_id IS DISTINCT FROM t.id THEN RAISE EXCEPTION 'attempt belongs to another task'; END IF;
   IF TG_OP='INSERT' THEN
     IF t.state<>'running' OR a.finished_at IS NOT NULL OR a.lease_expires_at<=clock_timestamp() THEN
        RAISE EXCEPTION 'stale execution lease'; END IF;
     SELECT (SELECT count(*) FROM collection_calls c JOIN collection_jobs job_lookup ON job_lookup.id=c.job_id WHERE job_lookup.task_id=t.id)
          + (SELECT count(*) FROM ai_executions WHERE task_id=t.id) INTO n;
     IF n>=t.max_external_calls THEN RAISE EXCEPTION 'BUDGET_EXHAUSTED'; END IF;
     IF TG_TABLE_NAME='collection_calls' THEN
       NEW.reserved_at:=clock_timestamp();
       IF NEW.outcome IS NOT NULL OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'call must reserve before completion'; END IF;
       IF NEW.sequence_no<>(SELECT count(*)+1 FROM collection_calls WHERE job_id=j.id) THEN RAISE EXCEPTION 'call sequence conflict'; END IF;
       IF (SELECT count(*) FROM collection_calls WHERE job_id=j.id)>=j.max_requests THEN
          RAISE EXCEPTION 'job budget exhausted'; END IF;
       IF j.plan_id IS NOT NULL AND t.execution_authorized_by IS DISTINCT FROM
          (SELECT authorized_by FROM collection_plans WHERE id=j.plan_id) THEN
          RAISE EXCEPTION 'plan authorizer changed'; END IF;
     ELSE
       NEW.started_at:=clock_timestamp();
       IF NEW.result_state IS NOT NULL OR NEW.finished_at IS NOT NULL THEN RAISE EXCEPTION 'AI must reserve before completion'; END IF;
       IF NEW.invocation_no<>(SELECT count(*)+1 FROM ai_executions WHERE attempt_id=a.id) THEN RAISE EXCEPTION 'AI invocation sequence conflict'; END IF;
     END IF;
   ELSIF (to_jsonb(OLD)->>'finished_at') IS NOT NULL OR
         (to_jsonb(OLD)->>'completed_at') IS NOT NULL THEN
     -- Explicit billing fields can be attached later; never rewrite a response.
     IF TG_TABLE_NAME='ai_executions' OR
       (to_jsonb(NEW)-ARRAY['billed_amount','currency','billing_reference']) IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['billed_amount','currency','billing_reference']) THEN
       RAISE EXCEPTION 'completed execution immutable'; END IF;
   END IF;
 END IF;
 RETURN NEW;
END $$;
