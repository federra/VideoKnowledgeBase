"""Prefetch same-org facts, never authorization decisions, for a single read request."""

from uuid import UUID

from sqlalchemy import select

from app.core.models import metadata


def fetch(c, org, name, field, ids):
    if not ids:
        return []
    table = metadata.tables[name]
    return [dict(v) for v in c.execute(select(table).where(
        table.c.org_id == org, table.c[field].in_(set(ids))
    )).mappings()]


def prepare(c, p, snapshots, auth):
    from app.intelligence.service import novel_raw_map

    if not snapshots:
        return
    auth._fresh()
    sources = fetch(c, p.org_id, 'sources', 'id', [s['source_id'] for s in snapshots])
    source_map = {s['id']:s for s in sources}
    jobs = fetch(c, p.org_id, 'collection_jobs', 'id', [s['job_id'] for s in snapshots])
    entries = fetch(c, p.org_id, 'snapshot_entries', 'snapshot_id', [s['id'] for s in snapshots])
    by_snapshot = {s['id']:[] for s in snapshots}
    for entry in entries:
        by_snapshot[entry['snapshot_id']].append(entry)
    for ident, rows in by_snapshot.items():
        auth.projections[('snapshot.entries',ident)] = sorted(rows,key=lambda r:r['position'])
    content_obs = fetch(c,p.org_id,'content_observations','id',[e['content_observation_id'] for e in entries if e['content_observation_id']])
    account_obs = fetch(c,p.org_id,'account_observations','id',[e['account_observation_id'] for e in entries if e['account_observation_id']])
    contents = fetch(c,p.org_id,'external_contents','id',[o['content_id'] for o in content_obs])
    accounts = fetch(c,p.org_id,'external_accounts','id',[o['account_id'] for o in account_obs])
    novel_jobs = [j['id'] for j in jobs if source_map[j['source_id']]['platform_code'] in ('fanqie','qidian','qimao')]
    raw_map = novel_raw_map(c,p.org_id,novel_jobs) if novel_jobs else {}
    for ident, ids in raw_map.items():
        auth.projections[('novel.raws',ident)] = ids
    raw_ids = {o['raw_asset_id'] for o in content_obs+account_obs}
    raw_ids.update(r for ids in raw_map.values() for r in ids)
    for job in jobs:
        try:
            raw_ids.add(UUID(job['safe_request']['raw_asset_id']))
        except (KeyError,ValueError,TypeError):
            pass
    raws = fetch(c,p.org_id,'raw_assets','id',list(raw_ids))
    for name, rows in [('intelligence_snapshots',snapshots),('collection_jobs',jobs),
                       ('snapshot_entries',entries),('content_observations',content_obs),
                       ('account_observations',account_obs),('external_contents',contents),
                       ('external_accounts',accounts),('sources',sources),('raw_assets',raws)]:
        auth.projections.update({('row',name,r['id']):r for r in rows})
        if name in ('sources','raw_assets'):
            auth.rows.update({(name,r['id']):r for r in rows})
    if raw_ids:
        ids=list(raw_ids)
        auth.raw_states.update({rid:None for rid in ids})
        auth.raw_states.update(dict(c.exec_driver_sql(
            "SELECT DISTINCT ON(raw_asset_id) raw_asset_id,event_kind FROM raw_asset_events WHERE org_id=%s AND raw_asset_id=ANY(%s) AND event_kind IN ('withdrawn','access_revoked','availability_restored') ORDER BY raw_asset_id,event_no DESC",(p.org_id,ids)).all()))
        nodes=['r:'+str(rid) for rid in ids]
        auth.parents.update({node:[] for node in nodes})
        for child,parent in c.exec_driver_sql('SELECT child,parent FROM cip_graph_edges(%s) WHERE child=ANY(%s)',(p.org_id,nodes)):
            auth.parents[child].append(parent)
