"""Bulk-load related rows, then keep per-item authorization before exposing them."""

from sqlalchemy import select

from app.core.models import metadata


def prepare(c, p, ids, az, candidate):
    def fetch(name, field, values):
        if not values:
            return []
        t = metadata.tables[name]
        return [
            dict(v)
            for v in c.execute(
                select(t).where(t.c.org_id == p.org_id, t.c[field].in_(values))
            ).mappings()
        ]

    identities = fetch("knowledge_items", "id", ids)
    publications = fetch("knowledge_publications", "knowledge_id", ids)
    pubs = {v["id"]: v for v in publications}
    rids = [
        v["current_revision_id"]
        if candidate
        else pubs[v["published_publication_id"]]["revision_id"]
        for v in identities
    ]
    revisions = fetch("knowledge_revisions", "id", rids)
    businesses = {rid: [] for rid in rids}
    evidence = {rid: [] for rid in rids}
    for v in fetch("knowledge_businesses", "revision_id", rids):
        businesses[v["revision_id"]].append(v["business_code"])
    for v in fetch("knowledge_evidence", "revision_id", rids):
        evidence[v["revision_id"]].append(v["evidence_id"])
    refs = fetch(
        "evidence_refs", "id", list({eid for values in evidence.values() for eid in values})
    )
    raws = fetch("raw_assets", "id", list({v["raw_asset_id"] for v in refs if v["raw_asset_id"]}))
    if raws:
        raw_ids = [v["id"] for v in raws]
        az.raw_states.update({rid: None for rid in raw_ids})
        az.raw_states.update(
            dict(
                c.exec_driver_sql(
                    "SELECT DISTINCT ON (raw_asset_id) raw_asset_id,event_kind FROM raw_asset_events "
                    "WHERE org_id=%s AND raw_asset_id=ANY(%s) "
                    "AND event_kind IN ('withdrawn','access_revoked','availability_restored') "
                    "ORDER BY raw_asset_id,event_no DESC",
                    (p.org_id, raw_ids),
                ).all()
            )
        )
        nodes = ["r:" + str(rid) for rid in raw_ids]
        az.parents.update({node: [] for node in nodes})
        for child, parent in c.exec_driver_sql(
            "SELECT child,parent FROM cip_graph_edges(%s) WHERE child=ANY(%s)",
            (p.org_id, nodes),
        ):
            az.parents[child].append(parent)
    for name, rows in [
        ("knowledge_items", identities),
        ("knowledge_revisions", revisions),
        ("evidence_refs", refs),
        ("raw_assets", raws),
    ]:
        az.rows.update({(name, v["id"]): v for v in rows})
    az.businesses.update(businesses)
    az.evidence.update(evidence)
    az.publications.update({v["id"]: v["revision_id"] for v in publications})
    published = {v["revision_id"]: v for v in publications}
    az.published.update({rid: rid in published for rid in rids})
    requests = {
        v["knowledge_revision_id"]: v["id"]
        for v in fetch("review_requests", "knowledge_revision_id", rids)
    }
    from app.knowledge.genre_explanations import load

    explanations = load(c, p, rids, az) if not candidate else {}
    return {
        rid: {
            "business_codes": sorted(businesses[rid]),
            "evidence_ids": sorted(set(evidence[rid])),
            "review_request_id": requests.get(rid),
            "release_mode": published.get(rid, {}).get("release_mode", "double_review"),
            "ai_explanation": explanations.get(rid),
        }
        for rid in rids
    }
