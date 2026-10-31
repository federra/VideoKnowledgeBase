-- Bound join-order planning inside these provenance helpers only.
ALTER FUNCTION cip_page_reuse_allowed(uuid,uuid,uuid) SET join_collapse_limit=1;
ALTER FUNCTION cip_hongguo_saved_allowed(uuid,uuid,uuid) SET join_collapse_limit=1;
