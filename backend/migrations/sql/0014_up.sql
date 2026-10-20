ALTER TABLE input_sets ADD COLUMN parsed_sources jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE input_sets ADD CONSTRAINT ck_input_sets_parsed_sources CHECK(jsonb_typeof(parsed_sources)='object');
CREATE FUNCTION cip_input_parsed_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE s input_sets; source record;
BEGIN
 SELECT * INTO s FROM input_sets WHERE org_id=NEW.org_id AND id=NEW.id;
 FOR source IN SELECT key,value FROM jsonb_each(s.parsed_sources) LOOP
  IF jsonb_typeof(source.value)<>'object' OR NOT(source.value ?& ARRAY['raw_asset_id','sha256']) OR source.value-ARRAY['raw_asset_id','sha256']<>'{}'::jsonb THEN
   RAISE EXCEPTION 'invalid frozen parsed source'; END IF;
  IF NOT EXISTS(SELECT 1 FROM input_set_items i JOIN artifact_versions v ON v.org_id=i.org_id AND v.id=i.artifact_version_id
   JOIN raw_assets r ON r.org_id=v.org_id AND r.parent_artifact_version_id=v.id JOIN tasks t ON t.org_id=r.org_id AND t.id=r.processing_task_id
   WHERE i.org_id=s.org_id AND i.input_set_id=s.id AND v.id=source.key::uuid AND v.body_text IS NULL
    AND r.id=(source.value->>'raw_asset_id')::uuid AND r.sha256=source.value->>'sha256' AND r.body_text IS NOT NULL
    AND r.origin='processing' AND r.asset_kind='text' AND t.kind='research.parse' AND t.state='succeeded') THEN
   RAISE EXCEPTION 'parsed source must match frozen material and successful parser'; END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_input_parsed AFTER INSERT ON input_sets DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cip_input_parsed_guard();
REVOKE EXECUTE ON FUNCTION cip_input_parsed_guard() FROM PUBLIC;
CREATE OR REPLACE FUNCTION cip_input_contains(organization uuid,input_id uuid,evidence uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 WITH RECURSIVE roots(node) AS (
  SELECT 'v:'||artifact_version_id FROM input_set_items WHERE org_id=organization AND input_set_id=input_id
  UNION SELECT 'r:'||(entry.value->>'raw_asset_id') FROM input_sets s CROSS JOIN LATERAL jsonb_each(s.parsed_sources) entry WHERE s.org_id=organization AND s.id=input_id
 ),reachable(node,path) AS (
  SELECT node,ARRAY[node] FROM roots
  UNION ALL SELECT g.parent,r.path||g.parent FROM reachable r JOIN cip_graph_edges(organization) g ON g.child=r.node
   WHERE NOT g.parent=ANY(r.path) AND cardinality(r.path)<=32
 ) SELECT EXISTS(SELECT 1 FROM reachable r JOIN evidence_refs e ON e.org_id=organization AND e.id=evidence
   WHERE r.node=COALESCE('r:'||e.raw_asset_id,'v:'||e.artifact_version_id))
$$;
