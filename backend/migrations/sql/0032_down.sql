-- Refuse to discard a rubric while immutable assessments still use it.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM topic_assessments WHERE rubric_version='genre-load-v3-inferred') THEN
  RAISE EXCEPTION 'cannot downgrade: inferred assessments exist';
 END IF;
END $$;
ALTER TABLE topic_assessments DROP CONSTRAINT ck_topic_assessments_0;
ALTER TABLE topic_assessments ADD CONSTRAINT ck_topic_assessments_0 CHECK (rubric_version='genre-load-v2');

CREATE OR REPLACE FUNCTION cip_topic_assessment_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE t tasks%ROWTYPE; e ai_executions%ROWTYPE; r topic_revisions%ROWTYPE;
 input jsonb; dim jsonb; i integer; scores integer[] := '{}'; content_sum integer; market_sum integer;
 expected text[] := ARRAY['emotion','conflict','contrast','antagonist','twist','audience','platform','acquisition','sequel','differentiation'];
BEGIN
 SELECT * INTO t FROM tasks WHERE org_id=NEW.org_id AND id=NEW.task_id;
 SELECT * INTO e FROM ai_executions WHERE org_id=NEW.org_id AND id=NEW.ai_execution_id;
 SELECT * INTO r FROM topic_revisions WHERE org_id=NEW.org_id AND id=NEW.topic_revision_id;
 SELECT body_text::jsonb INTO input FROM raw_assets WHERE org_id=NEW.org_id AND id=t.raw_asset_id;
 IF t.kind IS DISTINCT FROM 'topic.score' OR t.handler_version IS DISTINCT FROM '1'
 OR t.max_external_calls IS DISTINCT FROM 1 OR t.max_attempts IS DISTINCT FROM 1
 OR t.business_code IS DISTINCT FROM 'motion_comic'
 OR e.task_id IS DISTINCT FROM NEW.task_id OR e.result_state IS DISTINCT FROM 'completed'
 OR e.invocation_no IS DISTINCT FROM 1 OR e.config_revision_id::text IS DISTINCT FROM input->'config'->>'revision_id'
 OR NOT EXISTS (SELECT 1 FROM task_attempts a WHERE a.org_id=NEW.org_id AND a.id=e.attempt_id AND a.task_id=t.id)
 OR r.topic_id IS DISTINCT FROM NEW.topic_id OR NEW.created_by IS DISTINCT FROM t.execution_authorized_by
 OR input->>'topic_id' IS DISTINCT FROM NEW.topic_id::text
 OR input->>'revision_id' IS DISTINCT FROM NEW.topic_revision_id::text
 OR input->>'topic_version' IS DISTINCT FROM r.version_no::text
 OR input->>'fields_sha256' IS DISTINCT FROM r.content_sha256::text
 OR input->'fields' IS DISTINCT FROM r.fields OR input->'source_refs' IS DISTINCT FROM r.source_refs
 OR input->>'rubric_version' IS DISTINCT FROM NEW.rubric_version THEN
   RAISE EXCEPTION 'assessment exact task revision execution mismatch';
 END IF;
 IF jsonb_typeof(NEW.body->'dimensions') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.body->'dimensions')<>10
 OR jsonb_typeof(NEW.body->'limitations') IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'assessment invalid body';
 END IF;
 FOR i IN 0..9 LOOP
   dim := NEW.body->'dimensions'->i;
   IF dim->>'key' IS DISTINCT FROM expected[i+1]
   OR jsonb_typeof(dim->'analysis') IS DISTINCT FROM 'string' OR btrim(dim->>'analysis')=''
   OR NOT (dim ? 'score') THEN RAISE EXCEPTION 'assessment invalid dimension'; END IF;
   IF dim->'score' <> 'null'::jsonb THEN
     IF jsonb_typeof(dim->'score') IS DISTINCT FROM 'number'
     OR (dim->>'score') !~ '^[0-5]$' OR i>=5 THEN
       RAISE EXCEPTION 'assessment invalid score or unverified market evidence';
     END IF;
     scores := array_append(scores,(dim->>'score')::integer);
   ELSE scores := array_append(scores,NULL::integer); END IF;
 END LOOP;
 content_sum := CASE WHEN array_position(scores[1:5],NULL) IS NULL THEN scores[1]+scores[2]+scores[3]+scores[4]+scores[5] ELSE NULL END;
 market_sum := CASE WHEN array_position(scores[6:10],NULL) IS NULL THEN scores[6]+scores[7]+scores[8]+scores[9]+scores[10] ELSE NULL END;
 IF NOT (NEW.body ?& ARRAY['content_total','market_total','total'])
 OR NEW.body->'content_total' IS DISTINCT FROM coalesce(to_jsonb(content_sum),'null'::jsonb)
 OR NEW.body->'market_total' IS DISTINCT FROM coalesce(to_jsonb(market_sum),'null'::jsonb)
 OR NEW.body->'total' IS DISTINCT FROM coalesce(to_jsonb(content_sum+market_sum),'null'::jsonb) THEN
   RAISE EXCEPTION 'assessment totals must reflect unknown evidence';
 END IF;
 RETURN NEW;
END $$;
