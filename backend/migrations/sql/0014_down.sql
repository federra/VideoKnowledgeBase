DO $$ BEGIN IF EXISTS(SELECT 1 FROM input_sets WHERE parsed_sources<>'{}'::jsonb) THEN RAISE EXCEPTION 'Cannot downgrade frozen parsed sources; restore a consistent backup'; END IF; END $$;
CREATE OR REPLACE FUNCTION cip_input_contains(organization uuid,input_id uuid,evidence uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
 WITH RECURSIVE reachable(node,path) AS (
  SELECT 'v:'||artifact_version_id,ARRAY['v:'||artifact_version_id] FROM input_set_items WHERE org_id=organization AND input_set_id=input_id
  UNION ALL SELECT g.parent,r.path||g.parent FROM reachable r JOIN cip_graph_edges(organization) g ON g.child=r.node
   WHERE NOT g.parent=ANY(r.path) AND cardinality(r.path)<=32
 ) SELECT EXISTS(SELECT 1 FROM reachable r JOIN evidence_refs e ON e.org_id=organization AND e.id=evidence
   WHERE r.node=COALESCE('r:'||e.raw_asset_id,'v:'||e.artifact_version_id))
$$;
DROP TRIGGER zz_input_parsed ON input_sets;
DROP FUNCTION cip_input_parsed_guard();
ALTER TABLE input_sets DROP CONSTRAINT ck_input_sets_parsed_sources;
ALTER TABLE input_sets DROP COLUMN parsed_sources;
