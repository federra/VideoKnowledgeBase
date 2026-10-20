"""Exact revision sources; all dependencies checked under current authorization."""

from app.security.authorization import Authorizer
from app.security.errors import Denied


def sources(c, p, revision_id):
    az = Authorizer(c, p)
    try:
        v = az.read("knowledge_revisions", revision_id)
    except Denied as ex:
        if ex.code != "NOT_FOUND":
            raise
        v = az.candidate("knowledge_revisions", revision_id)
    evidence = (
        c.exec_driver_sql(
            "SELECT DISTINCT evidence_id FROM knowledge_evidence WHERE org_id=%s AND revision_id=%s ORDER BY evidence_id",
            (p.org_id, revision_id),
        )
        .scalars()
        .all()
    )
    items = []
    for eid in evidence:
        e = az.read("evidence_refs", eid)
        target = e["artifact_version_id"]
        raw = az.read("raw_assets", e["raw_asset_id"]) if e["raw_asset_id"] else None
        if raw and not target:
            target = raw["parent_artifact_version_id"]
        work = episode = version = business = None
        if target:
            av = az.read("artifact_versions", target)
            work = av["work_id"]
            business = az.row("works", work)["business_code"]
            version = av["version_no"]
            episode = c.exec_driver_sql(
                "SELECT episode_no_at_input FROM artifact_version_units WHERE org_id=%s AND artifact_version_id=%s ORDER BY unit_id LIMIT 1",
                (p.org_id, target),
            ).scalar_one_or_none()
        attribution = None
        if raw and raw["origin"] == "manual" and raw.get("body_text"):
            marker = "\n\n【人工提供出处，未独立核验】\n"
            if marker in raw["body_text"]:
                attribution = raw["body_text"].split(marker, 1)[1]
        items.append(
            {
                **{
                    k: e[k]
                    for k in [
                        "id",
                        "raw_asset_id",
                        "artifact_version_id",
                        "locator_kind",
                        "paragraph_no",
                        "page_no",
                        "start_ms",
                        "end_ms",
                        "quoted_text",
                    ]
                },
                "origin": raw["origin"] if raw else "material_version",
                "independently_verified": False,
                "attribution": attribution,
                "target_artifact_version_id": target,
                "work_id": work,
                "episode_no": episode,
                "material_version_no": version,
                "business_code": business,
            }
        )
    return {
        "revision_id": v["id"],
        "knowledge_id": v["knowledge_id"],
        "source_report_id": v["source_report_id"],
        "items": items,
    }
