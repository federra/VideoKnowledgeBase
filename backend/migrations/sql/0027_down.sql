-- Preserve every other function setting, including the existing search_path.
ALTER FUNCTION cip_page_reuse_allowed(uuid,uuid,uuid) RESET join_collapse_limit;
ALTER FUNCTION cip_hongguo_saved_allowed(uuid,uuid,uuid) RESET join_collapse_limit;
