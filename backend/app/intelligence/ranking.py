"""Strict sample board policy. Supplier read-count order is never assumed to be video views."""


def keyword_board(rows, keyword="漫剧", limit=10, *, default_rows=None):
    seen = {}
    for value in sorted(
        rows,
        key=lambda x: (
            str(x["entry"]["observation"].get("observed_at", "")),
            str(x["entry"]["id"]),
        ),
        reverse=True,
    ):
        obs = value["entry"]["observation"]
        seen.setdefault((obs["platform_code"], obs["platform_id"]), value)
    matches = [
        v for v in seen.values() if keyword in (v["entry"]["observation"].get("description") or "")
    ]
    missing = sum(v["entry"]["observation"]["view_count"] is None for v in matches)
    status = (
        "not_acquired"
        if not rows
        else "no_content_matches"
        if not matches
        else "insufficient_metrics"
        if missing
        else "ready"
    )
    ranked = (
        sorted(
            matches,
            key=lambda x: (
                -int(x["entry"]["observation"]["view_count"]),
                str(x["entry"]["observation"]["platform_id"]),
            ),
        )[:limit]
        if status == "ready"
        else []
    )
    if status == "insufficient_metrics" and default_rows:
        default_seen = set()
        ranked = []
        for value in sorted(default_rows, key=lambda x: x["entry"]["position"]):
            obs = value["entry"]["observation"]
            key = (obs["platform_code"], obs["platform_id"])
            if keyword not in (obs.get("description") or "") or key in default_seen:
                continue
            default_seen.add(key)
            ranked.append(value)
        ranked = ranked[:limit]
        if ranked:
            status = "default_order"
    return {
        "status": status,
        "items": ranked,
        "text_matches": len(matches),
        "missing_views": missing,
    }
