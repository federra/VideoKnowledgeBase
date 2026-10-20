-- Exact local-capture method, kind and input-role pairs; provider guards unchanged.
DO $migration$
DECLARE definition text; old_text text; new_text text;
BEGIN
IF EXISTS(SELECT 1 FROM collection_jobs WHERE safe_request->>'method'='qidian-browser-ax-v1') THEN RAISE EXCEPTION 'Browser captures exist; preserve provenance before downgrade'; END IF;
SELECT pg_get_functiondef('cip_validate()'::regprocedure) INTO definition;
old_text := $old$mi.role IN ('novel_saved_html','novel_browser_ax')$old$;
new_text := $new$mi.role='novel_saved_html'$new$;
IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>2 THEN RAISE EXCEPTION 'unexpected local provenance guard'; END IF;
definition := replace(definition,old_text,new_text);
old_text := $old$AND ((mj.safe_request->>'method'='qidian-desktop-html-v1' AND mj.safe_request->>'capture_kind'='user_saved_html' AND mi.role='novel_saved_html')
 OR (mj.safe_request->>'method'='qidian-browser-ax-v1' AND mj.safe_request->>'capture_kind'='browser_native_accessibility' AND mi.role='novel_browser_ax'))
 AND mj.safe_request->>'gender'='female'$old$;
new_text := $new$AND mj.safe_request->>'method'='qidian-desktop-html-v1' AND mj.safe_request->>'gender'='female'
 AND mj.safe_request->>'capture_kind'='user_saved_html'$new$;
IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>2 THEN RAISE EXCEPTION 'unexpected local provenance guard'; END IF;
definition := replace(definition,old_text,new_text);
EXECUTE definition;
END $migration$;
