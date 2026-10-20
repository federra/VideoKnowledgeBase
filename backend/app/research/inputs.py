"""Explicit immutable research inputs; never include human preference fields."""

from uuid import UUID

from app.collection.service import insert
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt


def read_input(c, p, ident, action="content.read"):
    refresh(c, p)
    az = Authorizer(c, p)
    value = az.read("input_sets", ident)
    az.require("works", value["work_id"], action)
    items = [
        dict(r)
        for r in c.exec_driver_sql(
            "SELECT artifact_version_id,role,position FROM input_set_items WHERE org_id=%s AND input_set_id=%s ORDER BY position",
            (p.org_id, ident),
        ).mappings()
    ]
    if not value["sealed_at"] or not items:
        raise Denied("INSUFFICIENT_MATERIAL")
    for item in items:
        az.read("artifact_versions", item["artifact_version_id"])
    return {**value, "items": items, "lock_version": "1"}


def create_input(c, p, key, request):
    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    work = az.require("works", request.work_id, "research.submit")
    az.require("works", work["id"], "content.write")
    if request.scope == "unit":
        unit = az.read("content_units", request.unit_id)
        if unit["work_id"] != work["id"]:
            raise Denied("NOT_FOUND")
    elif request.scope == "artifact":
        artifact = az.read("artifacts", request.artifact_id)
        if artifact["work_id"] != work["id"]:
            raise Denied("NOT_FOUND")
    frozen = []
    parsed_sources = {}
    for item in sorted(request.items, key=lambda i: i.position):
        version = az.read("artifact_versions", item.artifact_version_id)
        if version["work_id"] != work["id"] or not version["sealed_at"]:
            raise Denied("NOT_FOUND")
        if item.role == "primary":
            if request.scope == "artifact" and version["artifact_id"] != request.artifact_id:
                raise Denied("VALIDATION_FAILED")
            if (
                request.scope == "unit"
                and not c.exec_driver_sql(
                    "SELECT 1 FROM artifact_version_units WHERE org_id=%s AND artifact_version_id=%s AND unit_id=%s",
                    (p.org_id, version["id"], request.unit_id),
                ).first()
            ):
                raise Denied("VALIDATION_FAILED")
        if version["body_text"] is None:
            raw_id = c.exec_driver_sql(
                "SELECT r.id FROM raw_assets r JOIN tasks t ON t.org_id=r.org_id AND t.id=r.processing_task_id WHERE r.org_id=%s AND r.parent_artifact_version_id=%s AND r.asset_kind='text' AND t.kind='research.parse' AND t.state='succeeded' ORDER BY r.captured_at DESC,r.id DESC LIMIT 1",
                (p.org_id, version["id"]),
            ).scalar_one_or_none()
            if not raw_id:
                raise Denied("INSUFFICIENT_MATERIAL")
            raw = az.read("raw_assets", raw_id)
            parsed_sources[str(version["id"])] = {
                "raw_asset_id": str(raw_id),
                "sha256": raw["sha256"],
            }
        frozen.append({**item.model_dump(mode="json"), "content_sha256": version["content_sha256"]})
    manifest = {
        **request.model_dump(mode="json"),
        "items": frozen,
        "parsed_sources": parsed_sources,
        "normalization_version": 1,
        "total_episode_count_at_input": work["total_episode_count"],
    }
    sha = digest(manifest)

    def perform():
        existing = c.exec_driver_sql(
            "SELECT id FROM input_sets WHERE org_id=%s AND work_id=%s AND manifest_sha256=%s",
            (p.org_id, work["id"], sha),
        ).scalar_one_or_none()
        if existing:
            return {"id": str(existing)}
        ident = insert(
            c,
            "input_sets",
            p.org_id,
            work_id=work["id"],
            scope=request.scope,
            unit_id=request.unit_id,
            artifact_id=request.artifact_id,
            business_code=work["business_code"],
            manifest_sha256=sha,
            normalization_version=1,
            parsed_sources=parsed_sources,
            total_episode_count_at_input=work["total_episode_count"],
        )
        from app.core.models import metadata

        for item in request.items:
            c.execute(
                metadata.tables["input_set_items"]
                .insert()
                .values(
                    org_id=p.org_id, input_set_id=ident, work_id=work["id"], **item.model_dump()
                )
            )
        c.exec_driver_sql("SELECT cip_seal('input_sets',%s,%s)", (p.org_id, ident))
        audit(c, p.org_id, p.member_id, "research.input_frozen", "input_set", ident)
        return {"id": str(ident)}

    saved = receipt(c, p, "createInputSet", key, request.model_dump(mode="json"), perform)
    return read_input(c, p, UUID(saved["id"]))
