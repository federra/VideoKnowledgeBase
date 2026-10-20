"""Immutable evidence packages for a later research submission; no task or external call."""

from uuid import UUID

from app.collection.service import insert
from app.contracts.models import (
    FrozenResearchEvidence,
    ResearchEvidenceCreate,
    ResearchEvidencePackage,
)
from app.intelligence.feedback import entry_feedback, project, read_feedback
from app.intelligence.service import authorized, row, wire
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt


def context(c, p, entry_id, request):
    entry = row(c, "snapshot_entries", p.org_id, entry_id)
    snap = row(c, "intelligence_snapshots", p.org_id, entry["snapshot_id"])
    if (
        not snap["sealed_at"]
        or not entry["content_observation_id"]
        or request.snapshot_id != snap["id"]
        or request.business_code != snap["business_code"]
        or request.business_date != snap["business_date"]
    ):
        raise Denied("NOT_FOUND")
    if request.snapshot_version != snap["version_no"]:
        raise Denied("VERSION_CONFLICT")
    items = authorized(c, p, snap)
    selected = next(x["entry"] for x in items if x["entry"]["id"] == entry_id)
    obs = row(c, "content_observations", p.org_id, entry["content_observation_id"])
    return entry, snap, selected, obs


def assemble(c, p, entry_id, request, *, check_absence=False):
    _entry, snap, selected, obs = context(c, p, entry_id, request)
    feedback = {
        "entry_id": entry_id,
        "snapshot_id": snap["id"],
        "snapshot_version": snap["version_no"],
        "business_code": snap["business_code"],
        "business_date": snap["business_date"],
        "platform_code": selected["observation"]["platform_code"],
        "status": "not_acquired",
        "feedback_id": None,
        "feedback_version": None,
        "sampling_description": None,
        "coverage_note": None,
        "sample_count": None,
        "classified_count": None,
        "comments": [],
        "claims": [],
    }
    if request.feedback_id:
        full = read_feedback(c, p, request.feedback_id)
        if full["snapshot_id"] != snap["id"]:
            raise Denied("NOT_FOUND")
        if full["version_no"] != request.feedback_version:
            raise Denied("VERSION_CONFLICT")
        scoped = project(full, obs["content_id"])
        if not scoped["comments"]:
            raise Denied("NOT_FOUND")
        feedback.update(
            scoped,
            status="ready",
            feedback_id=full["id"],
            feedback_version=full["version_no"],
            sampling_description=full["sampling_description"],
            coverage_note=full["coverage_note"],
        )
        selected["feedback_id"] = full["id"]
    elif (
        check_absence
        and entry_feedback(c, p, entry_id, request.business_code, request.business_date)["status"]
        == "ready"
    ):
        raise Denied("VERSION_CONFLICT")
    return FrozenResearchEvidence(
        snapshot=wire(snap), entry=selected, content_id=obs["content_id"], feedback=feedback
    ).model_dump(mode="json")


def read_handoff(c, p, ident):
    refresh(c, p)
    value = row(c, "intelligence_handoffs", p.org_id, ident)
    body = value["body"]
    try:
        frozen = FrozenResearchEvidence.model_validate(body)
        request = ResearchEvidenceCreate(
            business_code=value["business_code"],
            business_date=value["business_date"],
            snapshot_id=value["snapshot_id"],
            snapshot_version=frozen.snapshot.version_no,
            feedback_id=value["feedback_id"],
            feedback_version=frozen.feedback.feedback_version,
        )
    except ValueError:
        raise Denied("SOURCE_UNAVAILABLE") from None
    expected = assemble(c, p, value["snapshot_entry_id"], request)
    if (
        value["schema_version"] != 1
        or body != expected
        or value["manifest_sha256"] != digest(body)
        or value["content_observation_id"] != frozen.entry.observation.id
    ):
        raise Denied("SOURCE_UNAVAILABLE")
    return ResearchEvidencePackage(
        **{k: value[k] for k in ("id", "created_at", "frozen_by", "manifest_sha256", "body")}
    ).model_dump(mode="json")


def create_handoff(c, p, entry_id, request, key, request_id=None):
    refresh(c, p)
    lock_org(c, p.org_id)
    entry, snap, _, _ = context(c, p, entry_id, request)
    Authorizer(c, p).require("sources", snap["source_id"], "research.submit")
    payload = {"entry_id": str(entry_id), **request.model_dump(mode="json")}

    def perform():
        body = assemble(c, p, entry_id, request, check_absence=True)
        ident = insert(
            c,
            "intelligence_handoffs",
            p.org_id,
            snapshot_id=snap["id"],
            snapshot_entry_id=entry_id,
            content_observation_id=entry["content_observation_id"],
            feedback_id=request.feedback_id,
            business_code=snap["business_code"],
            business_date=snap["business_date"],
            frozen_by=p.member_id,
            idempotency_key=str(key),
            schema_version=1,
            manifest_sha256=digest(body),
            body=body,
        )
        audit(
            c,
            p.org_id,
            p.member_id,
            "research.evidence_frozen",
            "intelligence_handoff",
            ident,
            request_id,
        )
        return {"id": str(ident)}

    saved = receipt(c, p, "freezeResearchEvidence", str(key), payload, perform)
    # Replay never skips original evidence authorization or returns cached sensitive body.
    return read_handoff(c, p, UUID(saved["id"]))
