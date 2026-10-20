"""Transactional research intake. No network/model calls; immutable material versions."""

import hashlib
from uuid import UUID, uuid4

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import compare_and_swap, create_task
from app.intelligence.service import row
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt
from app.tasks.service import input_digest


def target_work(c, p, target):
    az = Authorizer(c, p)
    if target.kind == "existing":
        work = az.require("works", target.work_id, "content.write")
        if work["lock_version"] != int(target.expected_lock_version):
            raise Denied("VERSION_CONFLICT")
        return work
    if not az.allowed(
        "content.write", {("org", str(p.org_id)), ("business", target.business_code)}
    ):
        raise Denied("ACCESS_DENIED")
    wid = insert(
        c,
        "works",
        p.org_id,
        business_code=target.business_code,
        work_number="W-" + uuid4().hex[:12],
        name=target.name,
        genre_tags=target.genre_tags,
        total_episode_count=target.total_episode_count,
        created_by=p.member_id,
    )
    audit(c, p.org_id, p.member_id, "work.created", "work", wid)
    return row(c, "works", p.org_id, wid)


def create_work(c, p, key, request):
    refresh(c, p)
    lock_org(c, p.org_id)
    from app.contracts.models import NewWork

    if not Authorizer(c, p).allowed(
        "content.write", {("org", str(p.org_id)), ("business", request.business_code)}
    ):
        raise Denied("ACCESS_DENIED")

    def perform():
        return {"id": str(target_work(c, p, NewWork(kind="new", **request.model_dump()))["id"])}

    saved = receipt(c, p, "createWork", key, request.model_dump(mode="json"), perform)
    return work_wire(Authorizer(c, p).read("works", UUID(saved["id"])))


def resolve(c, p, request, work_id=None):
    az = Authorizer(c, p)
    if request.origin == "text":
        return request.body_text, None, []
    if request.origin == "upload":
        f = az.read("file_objects", request.file_id)
        intake = c.exec_driver_sql(
            "SELECT work_id FROM file_intakes WHERE org_id=%s AND file_id=%s", (p.org_id, f["id"])
        ).scalar_one_or_none()
        if intake is None or (work_id is not None and intake != work_id):
            raise Denied("NOT_FOUND")
        az.require("works", intake, "content.write")
        if request.material_kind == "finished_video" and f["media_type"] != "video/mp4":
            raise Denied("VALIDATION_FAILED")
        return None, f["id"], []
    from urllib.parse import urlsplit

    try:
        u = urlsplit(request.url)
    except ValueError:
        raise Denied("VALIDATION_FAILED") from None
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise Denied("VALIDATION_FAILED")
    # Only supported, previously captured links. Never fetch arbitrary share pages or spend API budget.
    candidates = (
        c.exec_driver_sql(
            "SELECT o.* FROM content_observations o JOIN external_contents e ON e.id=o.content_id AND e.org_id=o.org_id WHERE o.org_id=%s AND o.original_url=%s ORDER BY o.observed_at DESC,o.id DESC",
            (p.org_id, request.url),
        )
        .mappings()
        .all()
    )
    for obs in candidates:
        try:
            az.read("raw_assets", obs["raw_asset_id"])
        except Denied:
            continue
        if obs["description"]:
            if request.material_kind != "reference":
                raise Denied("VALIDATION_FAILED")
            return obs["description"], None, [obs["raw_asset_id"]]
    raise Denied("SOURCE_UNAVAILABLE")


def make_unit(c, p, work, number):
    if number is None:
        return None
    if work["business_code"] != "motion_comic" or (
        work["total_episode_count"] and number > work["total_episode_count"]
    ):
        raise Denied("VALIDATION_FAILED")
    existing = c.exec_driver_sql(
        "SELECT id FROM content_units WHERE org_id=%s AND work_id=%s AND unit_kind=%s AND episode_no=%s",
        (p.org_id, work["id"], "episode", number),
    ).scalar_one_or_none()
    return existing or insert(
        c, "content_units", p.org_id, work_id=work["id"], unit_kind="episode", episode_no=number
    )


def material_version(c, p, work, request, body, file_id, sources):
    az = Authorizer(c, p)
    if request.material_kind == "finished_video" and not file_id:
        raise Denied("INSUFFICIENT_MATERIAL")
    unit = make_unit(c, p, work, request.episode_no)
    if request.artifact_id:
        artifact = az.require("artifacts", request.artifact_id, "content.write")
        if artifact["work_id"] != work["id"]:
            raise Denied("NOT_FOUND")
        if artifact["lock_version"] != int(request.expected_artifact_lock_version):
            raise Denied("VERSION_CONFLICT")
        if artifact["primary_unit_id"] != unit:
            raise Denied("VALIDATION_FAILED")
    else:
        aid = insert(
            c,
            "artifacts",
            p.org_id,
            work_id=work["id"],
            primary_unit_id=unit,
            material_number="M-" + uuid4().hex[:12],
            title=request.title,
            material_kind=request.material_kind,
            created_by=p.member_id,
        )
        artifact = row(c, "artifacts", p.org_id, aid)
    if file_id:
        az.read("file_objects", file_id)
        if (
            c.exec_driver_sql(
                "SELECT work_id FROM file_intakes WHERE org_id=%s AND file_id=%s",
                (p.org_id, file_id),
            ).scalar_one_or_none()
            != work["id"]
        ):
            raise Denied("NOT_FOUND")
    manifest = {
        "work_id": str(work["id"]),
        "artifact_id": str(artifact["id"]),
        "title": request.title,
        "material_kind": request.material_kind,
        "body_text": body,
        "file_id": str(file_id) if file_id else None,
        "sources": list(map(str, sources)),
        "unit_id": str(unit) if unit else None,
        "normalization_version": 1,
    }
    sha = digest(manifest)
    old = c.exec_driver_sql(
        "SELECT id FROM artifact_versions WHERE org_id=%s AND artifact_id=%s AND content_sha256=%s",
        (p.org_id, artifact["id"], sha),
    ).scalar_one_or_none()
    if old:
        return artifact, old, True
    version = c.exec_driver_sql(
        "SELECT coalesce(max(version_no),0)+1 FROM artifact_versions WHERE org_id=%s AND artifact_id=%s",
        (p.org_id, artifact["id"]),
    ).scalar_one()
    vid = insert(
        c,
        "artifact_versions",
        p.org_id,
        artifact_id=artifact["id"],
        work_id=work["id"],
        version_no=version,
        title=request.title,
        material_kind=request.material_kind,
        body_text=body,
        file_id=file_id,
        content_sha256=sha,
        created_by=p.member_id,
    )
    for raw in sources:
        az.read("raw_assets", raw)
        c.execute(
            metadata.tables["artifact_version_sources"]
            .insert()
            .values(org_id=p.org_id, artifact_version_id=vid, raw_asset_id=raw, role="reference")
        )
    if unit:
        c.execute(
            metadata.tables["artifact_version_units"]
            .insert()
            .values(
                org_id=p.org_id,
                artifact_version_id=vid,
                work_id=work["id"],
                unit_id=unit,
                episode_no_at_input=request.episode_no,
            )
        )
    c.exec_driver_sql("SELECT cip_seal('artifact_versions',%s,%s)", (p.org_id, vid))
    compare_and_swap(
        c,
        "artifacts",
        p.org_id,
        artifact["id"],
        artifact["lock_version"],
        {"current_version_id": vid, "title": request.title, "material_kind": request.material_kind},
    )
    return row(c, "artifacts", p.org_id, artifact["id"]), vid, False


def parse_task(c, p, work, vid):
    from app.processing.research import Parse

    existing = c.exec_driver_sql(
        "SELECT id FROM tasks WHERE org_id=%s AND kind='research.parse' AND idempotency_key=%s",
        (p.org_id, str(vid)),
    ).scalar_one_or_none()
    if existing:
        return existing
    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "research.parse",
        "handler_version": "1",
        "work_id": work["id"],
        "business_code": work["business_code"],
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_attempts": 1,
        "max_external_calls": 0,
        "idempotency_key": str(vid),
    }
    inputs = [{"role": "material", "artifact_version_id": vid}]
    values["input_sha256"] = input_digest(
        values, Parse().freeze(c, values, Authorizer(c, p), inputs=inputs)
    )
    create_task(c, values, inputs)
    return tid


def submit_record(
    c,
    p,
    key,
    work,
    artifact,
    vid,
    tid,
    origin,
    import_key,
    *,
    entry=None,
    feedback=None,
    handoff=None,
    assessment=None,
):
    sid = insert(
        c,
        "research_submissions",
        p.org_id,
        work_id=work["id"],
        artifact_version_id=vid,
        origin=origin,
        snapshot_entry_id=entry,
        feedback_id=feedback,
        handoff_id=handoff,
        submitted_by=p.member_id,
        task_id=tid,
        client_request_key=str(key),
        import_key=import_key,
        input_sha256=digest(
            {
                "version": str(vid),
                "handoff": str(handoff) if handoff else None,
                "assessment": assessment.model_dump(mode="json") if assessment else None,
            }
        ),
    )
    if assessment:
        insert(
            c,
            "preliminary_assessments",
            p.org_id,
            submission_id=sid,
            assessed_by=p.member_id,
            quality_grade=assessment.quality_grade,
            learning_tags=assessment.learning_tags,
            additional_learning=assessment.additional_learning,
            confirmed_business_code=work["business_code"],
            confirmed_genre_tags=assessment.genre_tags,
            work_name_at_submit=work["name"],
            total_episodes_at_submit=assessment.total_episode_count,
            episode_no_at_submit=assessment.episode_no,
        )
    c.exec_driver_sql("SELECT cip_seal('research_submissions',%s,%s)", (p.org_id, sid))
    audit(c, p.org_id, p.member_id, "research.submitted", "submission", sid)
    return sid


def direct_intake(c, p, key, request):
    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    if request.target.kind == "existing":
        target = az.require("works", request.target.work_id, "research.submit")
        az.require("works", target["id"], "content.write")
    else:
        for action in ("research.submit", "content.write"):
            if not az.allowed(
                action, {("org", str(p.org_id)), ("business", request.target.business_code)}
            ):
                raise Denied("ACCESS_DENIED")

    def perform():
        # Resolve before creating a work; unsupported links never leave empty containers.
        body, file_id, sources = resolve(
            c, p, request, request.target.work_id if request.target.kind == "existing" else None
        )
        if request.origin == "upload" and request.target.kind != "existing":
            raise Denied("VALIDATION_FAILED")
        work = target_work(c, p, request.target)
        artifact, vid, reused = material_version(c, p, work, request, body, file_id, sources)
        tid = parse_task(c, p, work, vid)
        sid = submit_record(
            c, p, key, work, artifact, vid, tid, request.origin, "material:" + str(artifact["id"])
        )
        return {
            "work_id": str(work["id"]),
            "artifact_id": str(artifact["id"]),
            "artifact_version_id": str(vid),
            "task_id": str(tid),
            "submission_id": str(sid),
            "reused": reused,
        }

    saved = receipt(c, p, "researchDirect", key, request.model_dump(mode="json"), perform)
    Authorizer(c, p).read("artifact_versions", UUID(saved["artifact_version_id"]))
    return {
        **saved,
        **{
            k: UUID(saved[k])
            for k in ("work_id", "artifact_id", "artifact_version_id", "task_id", "submission_id")
        },
    }


def add_material(c, p, key, work_id, request):
    refresh(c, p)
    lock_org(c, p.org_id)
    work = Authorizer(c, p).require("works", work_id, "research.submit")
    Authorizer(c, p).require("works", work_id, "content.write")

    def perform():
        body, file_id, sources = resolve(c, p, request, work_id)
        artifact, vid, reused = material_version(c, p, work, request, body, file_id, sources)
        tid = parse_task(c, p, work, vid)
        sid = submit_record(
            c, p, key, work, artifact, vid, tid, request.origin, "material:" + str(artifact["id"])
        )
        return {
            "work_id": str(work_id),
            "artifact_id": str(artifact["id"]),
            "artifact_version_id": str(vid),
            "task_id": str(tid),
            "submission_id": str(sid),
            "reused": reused,
        }

    saved = receipt(
        c,
        p,
        "researchMaterial",
        key,
        {"work_id": str(work_id), "request": request.model_dump(mode="json")},
        perform,
    )
    Authorizer(c, p).read("artifact_versions", UUID(saved["artifact_version_id"]))
    return {
        **saved,
        **{
            k: UUID(saved[k])
            for k in ("work_id", "artifact_id", "artifact_version_id", "task_id", "submission_id")
        },
    }


def work_wire(work):
    return {
        **{
            k: work[k]
            for k in (
                "id",
                "created_at",
                "updated_at",
                "business_code",
                "name",
                "genre_tags",
                "total_episode_count",
                "work_number",
                "latest_report_id",
            )
        },
        "lock_version": str(work["lock_version"]),
        "report_generation": str(work["report_generation"]),
    }


def parsing(c, p, vid):
    az = Authorizer(c, p)
    tasks = (
        c.exec_driver_sql(
            "SELECT t.* FROM tasks t JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id WHERE t.org_id=%s AND t.kind='research.parse' AND i.artifact_version_id=%s ORDER BY t.created_at DESC,t.id DESC",
            (p.org_id, vid),
        )
        .mappings()
        .all()
    )
    if not tasks:
        return None
    t = tasks[0]
    out = {
        "task_id": t["id"],
        "state": t["state"],
        "result_state": "failed" if t["state"] == "failed" else None,
        "safe_error_code": t["safe_error_code"],
        "paragraphs": [],
    }
    raw = (
        c.exec_driver_sql(
            "SELECT r.* FROM task_outputs o JOIN raw_assets r ON r.org_id=o.org_id AND r.id=o.raw_asset_id WHERE o.org_id=%s AND o.task_id=%s AND o.role='parsed_document'",
            (p.org_id, t["id"]),
        )
        .mappings()
        .one_or_none()
    )
    if raw:
        import json

        az.read("raw_assets", raw["id"])
        if hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]:
            raise Denied("SOURCE_UNAVAILABLE")
        body = json.loads(raw["body_text"])
        if body["artifact_version_id"] != str(vid):
            raise Denied("SOURCE_UNAVAILABLE")
        for para in body["paragraphs"]:
            az.read("evidence_refs", UUID(para["evidence_id"]))
        out.update(
            {
                k: body[k]
                for k in (
                    "result_state",
                    "media_kind",
                    "duration_ms",
                    "missing_inputs",
                    "paragraphs",
                )
            },
            raw_id=raw["id"],
        )
    return out


def detail(c, p, work_id):
    refresh(c, p)
    az = Authorizer(c, p)
    work = az.read("works", work_id)
    units = list(
        c.exec_driver_sql(
            "SELECT id,episode_no,title FROM content_units WHERE org_id=%s AND work_id=%s ORDER BY episode_no NULLS LAST,id",
            (p.org_id, work_id),
        ).mappings()
    )
    mats = []
    collected = set()
    processing = 0
    attention = 0
    for a in c.exec_driver_sql(
        "SELECT * FROM artifacts WHERE org_id=%s AND work_id=%s ORDER BY created_at,id",
        (p.org_id, work_id),
    ).mappings():
        versions = []
        for v in c.exec_driver_sql(
            "SELECT * FROM artifact_versions WHERE org_id=%s AND artifact_id=%s ORDER BY version_no DESC",
            (p.org_id, a["id"]),
        ).mappings():
            # Deny the whole view if any displayed dependency is no longer readable.
            az.read("artifact_versions", v["id"])
            info = parsing(c, p, v["id"])
            number = c.exec_driver_sql(
                "SELECT episode_no_at_input FROM artifact_version_units WHERE org_id=%s AND artifact_version_id=%s ORDER BY unit_id LIMIT 1",
                (p.org_id, v["id"]),
            ).scalar_one_or_none()
            submissions = []
            for sub in c.exec_driver_sql(
                "SELECT * FROM research_submissions WHERE org_id=%s AND artifact_version_id=%s ORDER BY created_at DESC,id DESC",
                (p.org_id, v["id"]),
            ).mappings():
                if sub["handoff_id"]:
                    from app.intelligence.handoff import read_handoff

                    read_handoff(c, p, sub["handoff_id"])
                assessment = (
                    c.exec_driver_sql(
                        "SELECT quality_grade,learning_tags,additional_learning,confirmed_genre_tags FROM preliminary_assessments WHERE org_id=%s AND submission_id=%s",
                        (p.org_id, sub["id"]),
                    )
                    .mappings()
                    .one_or_none()
                )
                submissions.append(
                    {
                        "id": sub["id"],
                        "origin": sub["origin"],
                        "created_at": sub["created_at"].isoformat(),
                        "assessment": dict(assessment) if assessment else None,
                    }
                )
            versions.append(
                {
                    **{
                        k: v[k]
                        for k in (
                            "id",
                            "version_no",
                            "title",
                            "material_kind",
                            "body_text",
                            "file_id",
                            "content_sha256",
                        )
                    },
                    "episode_no": number,
                    "parsing": info,
                    "submissions": submissions,
                }
            )
            if v["id"] == a["current_version_id"]:
                if number is not None and v["material_kind"] != "reference":
                    collected.add(number)
                if info and info["state"] in ("queued", "running", "cancel_requested"):
                    processing += 1
                elif (
                    not info
                    or info["state"] == "failed"
                    or info["result_state"] == "insufficient_evidence"
                ):
                    attention += 1
        current = next(x for x in versions if x["id"] == a["current_version_id"])
        mats.append(
            {
                "id": a["id"],
                "lock_version": str(a["lock_version"]),
                "material_number": a["material_number"],
                "title": a["title"],
                "current_version_id": a["current_version_id"],
                "versions": versions,
                "parsing": current["parsing"],
            }
        )
    stages = (
        c.exec_driver_sql(
            "SELECT state FROM tasks WHERE org_id=%s AND work_id=%s AND kind IN ('research.decompose','research.evaluate','research.predict') ORDER BY created_at DESC,id DESC",
            (p.org_id, work_id),
        )
        .scalars()
        .all()
    )
    processing += sum(state in ("queued", "running", "cancel_requested") for state in stages)
    # Parsing never increments analyzed coverage; only actual sealed report units can do that.
    analyzed = c.exec_driver_sql(
        "SELECT count(DISTINCT u.unit_id) FROM report_units u JOIN analysis_reports r ON r.org_id=u.org_id AND r.id=u.report_id WHERE r.org_id=%s AND r.work_id=%s AND r.sealed_at IS NOT NULL AND u.coverage_state='analyzed'",
        (p.org_id, work_id),
    ).scalar_one()
    return {
        **work_wire(work),
        "units": [dict(u) for u in units],
        "materials": mats,
        "collected_units": len(collected),
        "analyzed_units": analyzed,
        "material_count": len(mats),
        "processing_count": processing,
        "attention_count": attention,
        "author": None,
        "author_id": None,
    }


def list_works(c, p, filters):
    refresh(c, p)
    Authorizer(c, p)
    items = []
    for w in c.exec_driver_sql(
        "SELECT id FROM works WHERE org_id=%s AND business_code=%s ORDER BY created_at DESC,id DESC",
        (p.org_id, filters.business_code),
    ).scalars():
        try:
            full = detail(c, p, w)
        except Denied:
            continue
        items.append({k: v for k, v in full.items() if k not in ("units", "materials")})
    genres = sorted({g for w in items for g in w["genre_tags"]})
    counts = {
        "all": len(items),
        "processing": sum(bool(w["processing_count"]) for w in items),
        "attention": sum(bool(w["attention_count"] or not w["latest_report_id"]) for w in items),
        "review": 0,
        "reported": sum(bool(w["latest_report_id"]) for w in items),
    }
    if filters.q:
        q = filters.q.casefold()
        items = [
            w
            for w in items
            if any(
                q in str(w.get(k) or "").casefold()
                for k in ("name", "work_number", "author", "author_id")
            )
        ]
    if filters.genre:
        items = [w for w in items if filters.genre in w["genre_tags"]]
    if filters.status == "processing":
        items = [w for w in items if w["processing_count"]]
    elif filters.status == "attention":
        items = [w for w in items if w["attention_count"] or not w["latest_report_id"]]
    elif filters.status == "review":
        items = []
    elif filters.status == "reported":
        items = [w for w in items if w["latest_report_id"]]
    total = len(items)
    return {
        "items": items[(filters.page - 1) * 20 : filters.page * 20],
        "total": total,
        "page": filters.page,
        "pages": max(1, (total + 19) // 20),
        "counts": counts,
        "genres": genres,
    }


def intelligence_intake(c, p, key, request):
    from app.contracts.models import ResearchEvidenceCreate
    from app.intelligence.handoff import create_handoff, read_handoff
    from app.research.contracts import MaterialIntake

    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    entry = row(c, "snapshot_entries", p.org_id, request.snapshot_entry_id)
    snap = row(c, "intelligence_snapshots", p.org_id, entry["snapshot_id"])
    from app.intelligence.service import authorized

    authorized(c, p, snap)
    az.require("sources", snap["source_id"], "research.submit")
    if (
        request.confirmed_business_code != snap["business_code"]
        and not request.cross_business_confirmed
    ):
        raise Denied("VALIDATION_FAILED")
    if request.material_kind != "reference":
        raise Denied("INSUFFICIENT_MATERIAL")
    if request.target.kind == "existing":
        work = az.require("works", request.target.work_id, "content.write")
        az.require("works", work["id"], "research.submit")
        if work["lock_version"] != int(request.target.expected_lock_version):
            raise Denied("VERSION_CONFLICT")
        if (
            request.assessment.episode_no
            and work["total_episode_count"]
            and request.assessment.episode_no > work["total_episode_count"]
        ):
            raise Denied("VALIDATION_FAILED")
        if (
            request.assessment.total_episode_count is not None
            and request.assessment.total_episode_count != work["total_episode_count"]
        ):
            raise Denied("VERSION_CONFLICT")
        if work["business_code"] != request.confirmed_business_code:
            raise Denied("VALIDATION_FAILED")
    else:
        for action in ("content.write", "research.submit"):
            if not az.allowed(
                action, {("org", str(p.org_id)), ("business", request.confirmed_business_code)}
            ):
                raise Denied("ACCESS_DENIED")
    feedback_version = None
    if request.feedback_id:
        f = az.read("feedback_snapshots", request.feedback_id)
        feedback_version = f["version_no"]
    obs = row(c, "content_observations", p.org_id, entry["content_observation_id"])
    if not obs["description"]:
        raise Denied("INSUFFICIENT_MATERIAL")
    import_key = (
        "intelligence:"
        + str(obs["content_id"])
        + ":"
        + str(obs["id"])
        + ":"
        + request.confirmed_business_code
    )

    def perform():
        h = create_handoff(
            c,
            p,
            entry["id"],
            ResearchEvidenceCreate(
                business_code=snap["business_code"],
                business_date=snap["business_date"],
                snapshot_id=snap["id"],
                snapshot_version=snap["version_no"],
                feedback_id=request.feedback_id,
                feedback_version=feedback_version,
            ),
            str(key),
        )
        hid = UUID(str(h["id"]))
        target = request.target
        # Stable source identity, never fuzzy names. A pending imported source is reused.
        prior = (
            c.exec_driver_sql(
                "SELECT r.*,a.id AS artifact_id,a.lock_version AS artifact_lock FROM research_submissions r JOIN artifacts a ON a.org_id=r.org_id AND a.id=(SELECT artifact_id FROM artifact_versions WHERE id=r.artifact_version_id) JOIN works w ON w.org_id=r.org_id AND w.id=r.work_id WHERE r.org_id=%s AND r.import_key=%s AND w.latest_report_id IS NULL ORDER BY r.created_at DESC LIMIT 1",
                (p.org_id, import_key),
            )
            .mappings()
            .one_or_none()
        )
        if prior and (target.kind == "new" or prior["work_id"] == target.work_id):
            work = az.require("works", prior["work_id"], "content.write")
            az.require("works", work["id"], "research.submit")
            artifact = row(c, "artifacts", p.org_id, prior["artifact_id"])
            vid = prior["artifact_version_id"]
            tid = prior["task_id"]
            reused = True
        else:
            work = target_work(c, p, target)
            material = MaterialIntake(
                title=work["name"] + " · 来源简介",
                material_kind="reference",
                origin="text",
                body_text=obs["description"],
            )
            # A synopsis remains work-level even if the human mentions an episode; it is not episode footage.
            artifact, vid, reused = material_version(
                c, p, work, material, obs["description"], None, [obs["raw_asset_id"]]
            )
            tid = parse_task(c, p, work, vid)
        sid = submit_record(
            c,
            p,
            key,
            work,
            artifact,
            vid,
            tid,
            "intelligence",
            import_key,
            entry=entry["id"],
            feedback=request.feedback_id,
            handoff=hid,
            assessment=request.assessment,
        )
        return {
            "work_id": str(work["id"]),
            "artifact_id": str(artifact["id"]),
            "artifact_version_id": str(vid),
            "task_id": str(tid),
            "submission_id": str(sid),
            "reused": reused,
        }

    saved = receipt(c, p, "submitIntelligence", key, request.model_dump(mode="json"), perform)
    az.read("artifact_versions", UUID(saved["artifact_version_id"]))
    linked = row(c, "research_submissions", p.org_id, UUID(saved["submission_id"]))
    read_handoff(c, p, linked["handoff_id"])
    return {
        **saved,
        **{
            k: UUID(saved[k])
            for k in ("work_id", "artifact_id", "artifact_version_id", "task_id", "submission_id")
        },
    }
