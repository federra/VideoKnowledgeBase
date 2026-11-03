"""Operation-local memoization for read-only services; never shared across requests.

The existing org transaction lock is held for the entire operation. Time-based
session/grant expiry invalidates the memo even while that lock is held. Do not use
this object in a service which mutates data before its next authorization check.
"""

from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import active_grants, refresh

IMMUTABLE_SCALARS = {
    type(None),
    str,
    int,
    float,
    bool,
    bytes,
    UUID,
    date,
    datetime,
    time,
    timedelta,
    Decimal,
}


class ReadAuthorizer(Authorizer):
    def __init__(self, connection, principal):
        super().__init__(connection, principal)
        self.valid_until = None
        self._check_depth = 0
        self._reload()

    def _reload(self):
        session = refresh(self.c, self.p)
        self.grants = list(active_grants(self.c, self.p))
        self.transaction = self.c.get_transaction() if self.c is not None else None
        now = datetime.now(UTC)
        # A grant can expire while its SELECT is in flight. Never cache that
        # result without a deadline, even if SQL saw it as active earlier.
        self.grants = [g for g in self.grants if not g.get("expires_at") or g["expires_at"] > now]
        if session.get("expires_at") and session["expires_at"] <= now:
            raise Denied("AUTH_REQUIRED")
        deadlines = [
            g["expires_at"] for g in self.grants if g.get("expires_at") and g["expires_at"] > now
        ]
        if session.get("expires_at"):
            deadlines.append(session["expires_at"])
        self.valid_until = min(deadlines) if deadlines else None
        self.rows, self.checks, self.scope_rows = {}, {}, {}
        self.businesses, self.evidence, self.publications, self.published = {}, {}, {}, {}
        self.raw_states, self.parents = {}, {}
        self.projections = {}

    def _fresh(self):
        if (self.c is not None and self.c.get_transaction() is not self.transaction) or (
            self.valid_until is not None and datetime.now(UTC) >= self.valid_until
        ):
            self._reload()

    def _refresh(self):
        self._fresh()

    def _grants(self):
        self._fresh()
        return self.grants

    def row(self, kind, ident):
        self._fresh()
        key = (kind, ident)
        if key not in self.rows:
            self.rows[key] = super().row(kind, ident)
        return dict(self.rows[key])

    def scopes(self, kind, row):
        self._fresh()
        key = (kind, row["id"])
        if key not in self.scope_rows:
            self.scope_rows[key] = super().scopes(kind, row)
        return set(self.scope_rows[key])

    def check(self, kind, ident, action, path=()):
        self._fresh()
        # Include the path: a cached success must never bypass cycle/depth checks.
        key = (kind, ident, action, path)
        nested = self._check_depth > 0
        self._check_depth += 1
        try:
            if key not in self.checks:
                self.checks[key] = super().check(kind, ident, action, path)
            result = self.checks[key]
        finally:
            self._check_depth -= 1
        # Authorizer only reads recursive results; isolate every external caller,
        # including callers supplying their own provenance path.
        if nested:
            return result
        # Database identity rows contain only immutable scalar values. Their
        # outer mapping must still be copied; JSON/unknown values need deep copy.
        if all(type(value) in IMMUTABLE_SCALARS for value in result.values()):
            return dict(result)
        return deepcopy(result)

    def knowledge_businesses(self, rid):
        self._fresh()
        if rid not in self.businesses:
            self.businesses[rid] = super().knowledge_businesses(rid)
        return list(self.businesses[rid])

    def knowledge_evidence(self, rid):
        self._fresh()
        if rid not in self.evidence:
            self.evidence[rid] = super().knowledge_evidence(rid)
        return list(self.evidence[rid])

    def publication_revision(self, pid):
        self._fresh()
        if pid not in self.publications:
            self.publications[pid] = super().publication_revision(pid)
        return self.publications[pid]

    def is_published(self, rid):
        self._fresh()
        if rid not in self.published:
            self.published[rid] = super().is_published(rid)
        return self.published[rid]

    def raw_asset_state(self, ident):
        self._fresh()
        if ident not in self.raw_states:
            self.raw_states[ident] = super().raw_asset_state(ident)
        return self.raw_states[ident]

    def provenance_parents(self, node):
        self._fresh()
        if node not in self.parents:
            self.parents[node] = super().provenance_parents(node)
        return list(self.parents[node])

    def memo(self, key, load):
        """Derived read state shares the same transaction and grant expiry boundary."""
        self._fresh()
        if key not in self.projections:
            self.projections[key] = load()
        return self.projections[key]

    def _genre_links(self):
        def load():
            tasks, links = {}, {}
            for tid, raw, rid in self.c.exec_driver_sql(
                "SELECT t.id,t.raw_asset_id,i.knowledge_revision_id FROM tasks t "
                "JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id AND i.role='target' "
                "WHERE t.org_id=%s AND t.kind='knowledge.genre_explain' AND i.knowledge_revision_id IS NOT NULL",
                (self.p.org_id,),
            ):
                tasks.setdefault(tid, set()).add(rid)
                links.setdefault(("raw", raw), set()).add(rid)
            if tasks:
                for raw, tid in self.c.exec_driver_sql(
                    "SELECT id,processing_task_id FROM raw_assets WHERE org_id=%s AND processing_task_id=ANY(%s)",
                    (self.p.org_id, list(tasks)),
                ):
                    links.setdefault(("raw", raw), set()).update(tasks[tid])
                for tid, incoming, outgoing in self.c.exec_driver_sql(
                    "SELECT task_id,input_manifest_file_id,output_file_id FROM ai_executions WHERE org_id=%s AND task_id=ANY(%s)",
                    (self.p.org_id, list(tasks)),
                ):
                    for fid in (incoming, outgoing):
                        if fid:
                            links.setdefault(("file", fid), set()).update(tasks[tid])
            return links

        return self.memo("genre-dependencies", load)

    def genre_raw_dependencies(self, ident, processing_task_id):
        return set(self._genre_links().get(("raw", ident), ()))

    def genre_file_dependencies(self, ident):
        return set(self._genre_links().get(("file", ident), ()))

    def feedback_dependency_tasks(self, ident, *, file=False):
        def load():
            links = {}
            tasks = (
                self.c.exec_driver_sql(
                    "SELECT * FROM tasks WHERE org_id=%s AND kind='audience.feedback' AND handler_version IN ('2','3')",
                    (self.p.org_id,),
                )
                .mappings()
                .all()
            )
            by_id = {t["id"]: t for t in tasks}
            for t in tasks:
                links.setdefault(("raw", t["raw_asset_id"]), []).append(t)
            for t, a, b in self.c.exec_driver_sql(
                "SELECT e.task_id,e.input_manifest_file_id,e.output_file_id FROM ai_executions e JOIN tasks t ON t.id=e.task_id AND t.org_id=e.org_id WHERE t.org_id=%s AND t.kind='audience.feedback' AND t.handler_version IN ('2','3')",
                (self.p.org_id,),
            ):
                for f in (a, b):
                    if f:
                        links.setdefault(("file", f), []).append(by_id[t])
            return links

        return self.memo("feedback-dependencies", load).get(("file" if file else "raw", ident), [])

    def personal_dependencies(self, kind, ident):
        if kind not in ("tasks", "raw_assets", "file_objects"):
            return ()

        def load():
            links = {}

            def add(kind, ident, owners):
                if ident:
                    links.setdefault((kind, ident), set()).update(owners)

            tasks = list(
                self.c.exec_driver_sql(
                    "SELECT id,requested_by,raw_asset_id,file_id FROM tasks WHERE org_id=%s "
                    "AND kind IN ('topic.generate','topic.score')",
                    (self.p.org_id,),
                ).mappings()
            )
            owners = {t["id"]: t["requested_by"] for t in tasks}
            for task in tasks:
                add("tasks", task["id"], [task["requested_by"]])
                add("raw_assets", task["raw_asset_id"], [task["requested_by"]])
                add("file_objects", task["file_id"], [task["requested_by"]])
            if not tasks:
                return links
            for tid, raw in self.c.exec_driver_sql(
                "SELECT task_id,raw_asset_id FROM task_outputs WHERE org_id=%s "
                "AND task_id=ANY(%s) AND raw_asset_id IS NOT NULL",
                (self.p.org_id, list(owners)),
            ):
                add("raw_assets", raw, [owners[tid]])
            raw_ids = [ident for (kind, ident) in links if kind == "raw_assets"]
            for raw, tid, fid in self.c.exec_driver_sql(
                "SELECT id,processing_task_id,file_id FROM raw_assets WHERE org_id=%s "
                "AND (processing_task_id=ANY(%s) OR id=ANY(%s))",
                (self.p.org_id, list(owners), raw_ids),
            ):
                if tid in owners:
                    add("raw_assets", raw, [owners[tid]])
                add("file_objects", fid, links.get(("raw_assets", raw), ()))
            for tid, incoming, outgoing in self.c.exec_driver_sql(
                "SELECT task_id,input_manifest_file_id,output_file_id FROM ai_executions "
                "WHERE org_id=%s AND task_id=ANY(%s)",
                (self.p.org_id, list(owners)),
            ):
                for fid in (incoming, outgoing):
                    add("file_objects", fid, [owners[tid]])
            return links

        return tuple(self.memo("personal-dependencies", load).get((kind, ident), ()))
