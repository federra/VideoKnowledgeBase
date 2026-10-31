"""Fail-closed, current DB authorization for reusable read/query services.

This is deliberately not an HTTP CRUD service. Unknown kinds cannot be read by
organization admins either. Parent scopes never confer standalone file access.
"""

from uuid import UUID

from sqlalchemy import select

from app.core.models import metadata
from app.security.errors import Denied
from app.security.sessions import active_grants, refresh

ROOTS = {
    "works": "work",
    "sources": "source",
    "raw_assets": "raw_asset",
    "knowledge_items": "knowledge",
    "standards": "standard",
    "file_objects": "file",
    "tasks": "task",
}
WORK_KINDS = {
    "artifacts",
    "artifact_versions",
    "content_units",
    "input_sets",
    "analysis_reports",
    "quality_evaluations",
    "predictions",
}
SUPPORTED = set(ROOTS) | WORK_KINDS | {"knowledge_revisions", "standard_revisions", "evidence_refs"}
ORG_ONLY = {"member.manage", "role.manage", "model.configure", "audit.read"}


class Authorizer:
    def __init__(self, connection, principal, *, include_recycled=False):
        self.c, self.p = connection, principal
        self.include_recycled = include_recycled

    def row(self, kind, ident):
        if kind not in SUPPORTED:
            raise Denied("NOT_FOUND")
        t = metadata.tables[kind]
        row = (
            self.c.execute(select(t).where(t.c.org_id == self.p.org_id, t.c.id == ident))
            .mappings()
            .one_or_none()
        )
        if not row:
            raise Denied("NOT_FOUND")
        return dict(row)

    def scopes(self, kind, row):
        scopes = {("org", str(self.p.org_id))}
        if kind in ROOTS:
            scopes.add((ROOTS[kind], str(row["id"])))
        if kind in WORK_KINDS:
            work_id = row.get("work_id")
            if work_id is None:
                work_id = self.row("input_sets", row["input_set_id"])["work_id"]
            scopes |= self.scopes("works", self.row("works", work_id))
        elif kind == "standard_revisions":
            scopes |= self.scopes("standards", self.row("standards", row["standard_id"]))
        elif kind == "knowledge_revisions":
            scopes.add(("knowledge", str(row["knowledge_id"])))
            scopes |= {("business", code) for code in self.knowledge_businesses(row["id"])}
        elif kind == "evidence_refs":
            for field, target in [
                ("raw_asset_id", "raw_assets"),
                ("artifact_version_id", "artifact_versions"),
            ]:
                if row[field]:
                    scopes |= self.scopes(target, self.row(target, row[field]))
        elif kind == "raw_assets" and row["collection_job_id"]:
            job = metadata.tables["collection_jobs"]
            source = self.c.execute(
                select(job.c.source_id).where(
                    job.c.org_id == self.p.org_id, job.c.id == row["collection_job_id"]
                )
            ).scalar_one()
            scopes |= self.scopes("sources", self.row("sources", source))
        if kind not in {
            "knowledge_items",
            "knowledge_revisions",
            "file_objects",
            "tasks",
        } and row.get("business_code"):
            scopes.add(("business", row["business_code"]))
        return scopes

    def knowledge_businesses(self, rid):
        t = metadata.tables["knowledge_businesses"]
        return list(
            self.c.execute(
                select(t.c.business_code).where(t.c.org_id == self.p.org_id, t.c.revision_id == rid)
            ).scalars()
        )

    def knowledge_evidence(self, rid):
        t = metadata.tables["knowledge_evidence"]
        return list(
            self.c.execute(
                select(t.c.evidence_id).where(t.c.org_id == self.p.org_id, t.c.revision_id == rid)
            ).scalars()
        )

    def publication_revision(self, pid):
        t = metadata.tables["knowledge_publications"]
        return self.c.execute(
            select(t.c.revision_id).where(t.c.org_id == self.p.org_id, t.c.id == pid)
        ).scalar_one_or_none()

    def is_published(self, rid):
        t = metadata.tables["knowledge_publications"]
        return bool(
            self.c.execute(
                select(t.c.id).where(t.c.org_id == self.p.org_id, t.c.revision_id == rid)
            ).first()
        )

    def _refresh(self):
        return refresh(self.c, self.p)

    def _grants(self):
        return active_grants(self.c, self.p)

    def allowed(self, action, scopes):
        return any(
            g["action_code"] == action
            and (
                (g["scope_kind"] == "org")
                or (
                    action not in ORG_ONLY
                    and (
                        g["scope_kind"],
                        str(
                            g["business_code"]
                            if g["scope_kind"] == "business"
                            else g.get(g["scope_kind"] + "_id")
                        ),
                    )
                    in scopes
                )
            )
            for g in self._grants()
        )

    def raw_asset_state(self, ident):
        e = metadata.tables["raw_asset_events"]
        return self.c.execute(
            select(e.c.event_kind)
            .where(
                e.c.org_id == self.p.org_id,
                e.c.raw_asset_id == ident,
                e.c.event_kind.in_(["withdrawn", "access_revoked", "availability_restored"]),
            )
            .order_by(e.c.event_no.desc())
            .limit(1)
        ).scalar_one_or_none()

    def provenance_parents(self, node):
        return list(
            self.c.exec_driver_sql(
                "SELECT parent FROM cip_graph_edges(%s) WHERE child=%s",
                (self.p.org_id, node),
            ).scalars()
        )

    def check(self, kind, ident, action, path=()):
        node = (kind, ident)
        if node in path or len(path) >= 32:
            raise Denied("PROVENANCE_DEPTH_EXCEEDED")
        path = (*path, node)
        row = self.row(kind, ident)
        scopes = self.scopes(kind, row)
        if kind in ("knowledge_items", "knowledge_revisions"):
            identity = (
                row
                if kind == "knowledge_items"
                else self.row("knowledge_items", row["knowledge_id"])
            )
            if identity.get("purged_at") is not None or (
                not self.include_recycled and identity.get("recycled_at") is not None
            ):
                raise Denied("NOT_FOUND")
        if kind == "knowledge_items":
            # Formal and candidate entry points are explicit and never substitute for
            # one another. Every subsequent action uses the exact selected Revision.
            if action == "knowledge.candidate.read":
                revision = row["current_revision_id"]
            else:
                revision = self.publication_revision(row["published_publication_id"])
            if not revision:
                raise Denied("NOT_FOUND")
            revision_row = self.check("knowledge_revisions", revision, action, path)
            scopes |= self.scopes("knowledge_revisions", revision_row)
            row = {**row, "title": revision_row["title"], "current_revision_id": revision}
        elif kind == "knowledge_revisions" and action != "knowledge.candidate.read":
            published = self.is_published(ident)
            if not published:
                raise Denied("NOT_FOUND")
        if not self.allowed(action, scopes):
            raise Denied("NOT_FOUND")
        if kind == "file_objects" and row["validation_state"] != "accepted":
            raise Denied("NOT_FOUND")
        if kind == "file_objects":
            self._genre_file_sources(ident, path)
            self._feedback_sources(ident, file=True)
        if kind == "raw_assets":
            state = self.raw_asset_state(ident)
            if state in ("withdrawn", "access_revoked"):
                raise Denied("NOT_FOUND")
            if row["origin"] == "manual" and '"match_key"' in (row.get("body_text") or ""):
                self._feedback_sources(ident)
            # Genre gloss inputs/outputs retain the full knowledge dependency set.
            # Generic raw provenance alone only follows raw/material edges.
            dependencies = (
                self.genre_raw_dependencies(ident, row.get("processing_task_id"))
                if row["origin"] in ("manual", "processing")
                and (row.get("body_text") or "").lstrip().startswith("{")
                else ()
            )
            for rid in dependencies:
                self.check("knowledge_revisions", rid, "content.read", path)
        for field in ("file_id", "cover_file_id"):
            if row.get(field):
                self._file(row[field], scopes, path=path)
        if kind in ("raw_assets", "artifact_versions"):
            prefix = "r:" if kind == "raw_assets" else "v:"
            edges = self.provenance_parents(prefix + str(ident))
            for parent in edges:
                self.check(
                    "raw_assets" if parent.startswith("r:") else "artifact_versions",
                    UUID(parent[2:]),
                    "evidence.read",
                    path,
                )
        if kind in ("analysis_reports", "quality_evaluations", "predictions", "input_sets"):
            items = metadata.tables["input_set_items"]
            input_id = ident if kind == "input_sets" else row["input_set_id"]
            for version in self.c.execute(
                select(items.c.artifact_version_id).where(
                    items.c.org_id == self.p.org_id, items.c.input_set_id == input_id
                )
            ).scalars():
                self.check("artifact_versions", version, "evidence.read", path)
        if kind == "input_sets":
            for source in row.get("parsed_sources", {}).values():
                self.check("raw_assets", UUID(source["raw_asset_id"]), "evidence.read", path)
        if kind == "evidence_refs":
            for field, target in [
                ("raw_asset_id", "raw_assets"),
                ("artifact_version_id", "artifact_versions"),
            ]:
                if row[field]:
                    self.check(target, row[field], "evidence.read", path)
        if kind == "knowledge_revisions":
            for evidence in self.knowledge_evidence(ident):
                self.check("evidence_refs", evidence, "evidence.read", path)
            if row["source_report_id"]:
                self.check("analysis_reports", row["source_report_id"], "evidence.read", path)
        if kind == "artifacts" and row["current_version_id"]:
            self.check("artifact_versions", row["current_version_id"], action, path)
        return row

    def read(self, kind, ident):
        self._refresh()
        action = {
            "file_objects": "file.read",
            "tasks": "task.read",
            "raw_assets": "evidence.read",
            "evidence_refs": "evidence.read",
            "standards": "standard.read",
            "standard_revisions": "standard.read",
        }.get(kind, "content.read")
        row = self.check(kind, ident, action)
        if kind == "tasks":
            # Task-only grants never reveal inputs, provider bodies, secrets or outputs.
            return {k: row[k] for k in ["id", "state", "kind", "created_at", "lock_version"]}
        return row

    def candidate(self, kind, ident):
        if kind not in ("knowledge_items", "knowledge_revisions"):
            raise Denied("VALIDATION_FAILED")
        self._refresh()
        return self.check(kind, ident, "knowledge.candidate.read")

    def require(self, kind, ident, action, *, candidate=False):
        # Mutating knowledge must explicitly select its candidate; formal operations
        # such as export continue to bind the published revision, even when a newer
        # candidate belongs to a different business.
        if (
            kind in ("knowledge_items", "knowledge_revisions")
            and action
            in {"knowledge.edit", "knowledge.review", "knowledge.review.run", "knowledge.publish"}
            and not candidate
        ):
            raise Denied("VALIDATION_FAILED")
        row = self.candidate(kind, ident) if candidate else self.read(kind, ident)
        scopes = self.scopes(kind, row)
        if kind == "knowledge_items":
            scopes |= self.scopes(
                "knowledge_revisions", self.row("knowledge_revisions", row["current_revision_id"])
            )
        if not self.allowed(action, scopes):
            raise Denied("ACCESS_DENIED")
        return row

    def _feedback_sources(self, ident, *, file=False):
        for task in self.feedback_dependency_tasks(ident, file=file):
            if file:
                # The manifest itself may also be withdrawn independently.
                self.check("raw_assets", task["raw_asset_id"], "evidence.read")
            else:
                from app.intelligence.feedback_v2 import frozen

                frozen(self.c, self.p, task, auth=self if hasattr(self, "memo") else None)

    def feedback_dependency_tasks(self, ident, *, file=False):
        if file:
            query = "SELECT DISTINCT t.* FROM tasks t JOIN ai_executions e ON e.org_id=t.org_id AND e.task_id=t.id WHERE t.org_id=%s AND t.kind='audience.feedback' AND t.handler_version IN ('2','3') AND (e.input_manifest_file_id=%s OR e.output_file_id=%s)"
            params = (self.p.org_id, ident, ident)
        else:
            query = "SELECT * FROM tasks WHERE org_id=%s AND kind='audience.feedback' AND handler_version IN ('2','3') AND raw_asset_id=%s"
            params = (self.p.org_id, ident)
        return self.c.exec_driver_sql(query, params).mappings().all()

    def _genre_file_sources(self, ident, path):
        for rid in self.genre_file_dependencies(ident):
            self.check("knowledge_revisions", rid, "content.read", path)

    def genre_raw_dependencies(self, ident, processing_task_id):
        return self.c.exec_driver_sql(
            "SELECT DISTINCT i.knowledge_revision_id FROM tasks t JOIN task_inputs i "
            "ON i.org_id=t.org_id AND i.task_id=t.id AND i.role='target' "
            "WHERE t.org_id=%s AND t.kind='knowledge.genre_explain' "
            "AND (t.raw_asset_id=%s OR t.id=%s) AND i.knowledge_revision_id IS NOT NULL",
            (self.p.org_id, ident, processing_task_id),
        ).scalars()

    def genre_file_dependencies(self, ident):
        return self.c.exec_driver_sql(
            "SELECT DISTINCT i.knowledge_revision_id FROM ai_executions e "
            "JOIN tasks t ON t.org_id=e.org_id AND t.id=e.task_id "
            "JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id AND i.role='target' "
            "WHERE e.org_id=%s AND t.kind='knowledge.genre_explain' "
            "AND (e.input_manifest_file_id=%s OR e.output_file_id=%s) "
            "AND i.knowledge_revision_id IS NOT NULL",
            (self.p.org_id, ident, ident),
        ).scalars()

    def _file(self, ident, parent_scopes=None, *, path=()):
        row = self.row("file_objects", ident)
        scopes = self.scopes("file_objects", row) | (parent_scopes or set())
        if row["validation_state"] != "accepted" or not self.allowed("file.read", scopes):
            raise Denied("NOT_FOUND")
        node = ("file_objects", ident)
        if node in path or len(path) >= 32:
            raise Denied("PROVENANCE_DEPTH_EXCEEDED")
        self._genre_file_sources(ident, (*path, node))
        self._feedback_sources(ident, file=True)
        return row

    def file(self, ident, parent=None):
        self._refresh()
        scopes = None
        if parent:
            row = self.read(*parent)
            associated = ident in (row.get("file_id"), row.get("cover_file_id"))
            if parent[0] == "works" and not associated:
                t = metadata.tables["file_intakes"]
                associated = bool(
                    self.c.execute(
                        select(t.c.file_id).where(
                            t.c.org_id == self.p.org_id,
                            t.c.work_id == parent[1],
                            t.c.file_id == ident,
                        )
                    ).first()
                )
            if not associated:
                raise Denied("NOT_FOUND")
            scopes = self.scopes(parent[0], row)
        return self._file(ident, scopes)

    def list(self, kind, *, q=None, limit=100, offset=0, candidate=False):
        self._refresh()
        if kind not in SUPPORTED or not 1 <= limit <= 100 or offset < 0:
            raise Denied("VALIDATION_FAILED")
        if candidate and kind not in ("knowledge_items", "knowledge_revisions"):
            raise Denied("VALIDATION_FAILED")
        t = metadata.tables[kind]
        query = select(t.c.id).where(t.c.org_id == self.p.org_id)
        if q and kind != "knowledge_items":
            fields = [t.c[k] for k in ["name", "title", "body_text"] if k in t.c]
            if not fields:
                raise Denied("VALIDATION_FAILED")
            from sqlalchemy import or_

            query = query.where(or_(*(f.contains(q, autoescape=True) for f in fields)))
        # Low-volume baseline: filter the full candidate set before counts/pagination.
        # No output/body/aggregate is emitted before dependency checks.
        result = []
        for ident in self.c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc())).scalars():
            try:
                row = self.candidate(kind, ident) if candidate else self.read(kind, ident)
                if q and kind == "knowledge_items" and q not in row["title"]:
                    continue
                result.append(row)
            except Denied as exc:
                if exc.code != "NOT_FOUND":
                    raise
        return result[offset : offset + limit]
