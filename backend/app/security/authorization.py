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
    def __init__(self, connection, principal):
        self.c, self.p = connection, principal

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
            t = metadata.tables["knowledge_businesses"]
            scopes |= {
                ("business", code)
                for code in self.c.execute(
                    select(t.c.business_code).where(
                        t.c.org_id == self.p.org_id, t.c.revision_id == row["id"]
                    )
                ).scalars()
            }
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
            for g in active_grants(self.c, self.p)
        )

    def check(self, kind, ident, action, path=()):
        node = (kind, ident)
        if node in path or len(path) >= 32:
            raise Denied("PROVENANCE_DEPTH_EXCEEDED")
        path = (*path, node)
        row = self.row(kind, ident)
        scopes = self.scopes(kind, row)
        if kind == "knowledge_items":
            # Formal and candidate entry points are explicit and never substitute for
            # one another. Every subsequent action uses the exact selected Revision.
            if action == "knowledge.candidate.read":
                revision = row["current_revision_id"]
            else:
                pub = metadata.tables["knowledge_publications"]
                revision = self.c.execute(
                    select(pub.c.revision_id).where(
                        pub.c.org_id == self.p.org_id, pub.c.id == row["published_publication_id"]
                    )
                ).scalar_one_or_none()
            if not revision:
                raise Denied("NOT_FOUND")
            revision_row = self.check("knowledge_revisions", revision, action, path)
            scopes |= self.scopes("knowledge_revisions", revision_row)
            row = {**row, "title": revision_row["title"], "current_revision_id": revision}
        elif kind == "knowledge_revisions" and action != "knowledge.candidate.read":
            pub = metadata.tables["knowledge_publications"]
            published = self.c.execute(
                select(pub.c.id).where(pub.c.org_id == self.p.org_id, pub.c.revision_id == ident)
            ).first()
            if not published:
                raise Denied("NOT_FOUND")
        if not self.allowed(action, scopes):
            raise Denied("NOT_FOUND")
        if kind == "file_objects" and row["validation_state"] != "accepted":
            raise Denied("NOT_FOUND")
        if kind == "raw_assets":
            e = metadata.tables["raw_asset_events"]
            state = self.c.execute(
                select(e.c.event_kind)
                .where(
                    e.c.org_id == self.p.org_id,
                    e.c.raw_asset_id == ident,
                    e.c.event_kind.in_(["withdrawn", "access_revoked", "availability_restored"]),
                )
                .order_by(e.c.event_no.desc())
                .limit(1)
            ).scalar_one_or_none()
            if state in ("withdrawn", "access_revoked"):
                raise Denied("NOT_FOUND")
        for field in ("file_id", "cover_file_id"):
            if row.get(field):
                self._file(row[field], scopes)
        if kind in ("raw_assets", "artifact_versions"):
            prefix = "r:" if kind == "raw_assets" else "v:"
            edges = self.c.exec_driver_sql(
                "SELECT parent FROM cip_graph_edges(%s) WHERE child=%s",
                (self.p.org_id, prefix + str(ident)),
            ).scalars()
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
            links = metadata.tables["knowledge_evidence"]
            for evidence in self.c.execute(
                select(links.c.evidence_id).where(
                    links.c.org_id == self.p.org_id, links.c.revision_id == ident
                )
            ).scalars():
                self.check("evidence_refs", evidence, "evidence.read", path)
            if row["source_report_id"]:
                self.check("analysis_reports", row["source_report_id"], "evidence.read", path)
        if kind == "artifacts" and row["current_version_id"]:
            self.check("artifact_versions", row["current_version_id"], action, path)
        return row

    def read(self, kind, ident):
        refresh(self.c, self.p)
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
        refresh(self.c, self.p)
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

    def _file(self, ident, parent_scopes=None):
        row = self.row("file_objects", ident)
        scopes = self.scopes("file_objects", row) | (parent_scopes or set())
        if row["validation_state"] != "accepted" or not self.allowed("file.read", scopes):
            raise Denied("NOT_FOUND")
        return row

    def file(self, ident, parent=None):
        refresh(self.c, self.p)
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
        refresh(self.c, self.p)
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
