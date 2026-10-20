-- Exact local-capture method, kind and input-role pairs; provider guards unchanged.
DO $migration$
DECLARE definition text; old_text text; new_text text;
BEGIN
SELECT pg_get_functiondef('cip_validate()'::regprocedure) INTO definition;
old_text := $old$mi.role='novel_saved_html'$old$;
new_text := $new$mi.role IN ('novel_saved_html','novel_browser_ax')$new$;
IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>2 THEN RAISE EXCEPTION 'unexpected local provenance guard'; END IF;
definition := replace(definition,old_text,new_text);
old_text := $old$AND mj.safe_request->>'method'='qidian-desktop-html-v1' AND mj.safe_request->>'gender'='female'
 AND mj.safe_request->>'capture_kind'='user_saved_html'$old$;
new_text := $new$AND ((mj.safe_request->>'method'='qidian-desktop-html-v1' AND mj.safe_request->>'capture_kind'='user_saved_html' AND mi.role='novel_saved_html')
 OR (mj.safe_request->>'method'='qidian-browser-ax-v1' AND mj.safe_request->>'capture_kind'='browser_native_accessibility' AND mi.role='novel_browser_ax'))
 AND mj.safe_request->>'gender'='female'$new$;
IF (length(definition)-length(replace(definition,old_text,'')))/length(old_text)<>2 THEN RAISE EXCEPTION 'unexpected local provenance guard'; END IF;
definition := replace(definition,old_text,new_text);
EXECUTE definition;
END $migration$;
