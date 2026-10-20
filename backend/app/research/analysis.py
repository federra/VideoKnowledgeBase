"""Frozen material analysis orchestration; approval and execution are separate facts."""

import hashlib
import json
from uuid import UUID, uuid4

from app.collection.service import insert
from app.core.repository import compare_and_swap, create_task
from app.intelligence.service import row
from app.research.inputs import read_input
from app.research.stage_model import output_schema, system_prompt
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt
from app.tasks.service import input_digest


def parameters(purpose):
    return {
        "definition_version": "research." + purpose + ".v2",
        "system_sha256": hashlib.sha256(system_prompt(purpose).encode()).hexdigest(),
        "max_output_tokens": 2048,
    }


def approved_standard(c, p, kind, revision=None, business="motion_comic"):
    az = Authorizer(c, p)
    if revision is None:
        rows = (
            c.exec_driver_sql(
                "SELECT active_revision_id FROM standards WHERE org_id=%s AND kind=%s AND business_code=%s AND active_revision_id IS NOT NULL ORDER BY code,id",
                (p.org_id, kind, business),
            )
            .scalars()
            .all()
        )
        if len(rows) != 1:
            raise Denied("STANDARD_NOT_APPROVED")
        revision = rows[0]
    rev = az.read("standard_revisions", revision)
    standard = az.read("standards", rev["standard_id"])
    if standard["kind"] != kind or standard["business_code"] != business:
        raise Denied("STANDARD_NOT_APPROVED")
    approved = c.exec_driver_sql(
        "SELECT 1 FROM review_requests r JOIN review_heads h ON h.org_id=r.org_id AND h.request_id=r.id AND h.reviewer_kind='human' JOIN review_decisions d ON d.org_id=h.org_id AND d.id=h.decision_id WHERE r.org_id=%s AND r.standard_revision_id=%s AND r.purpose='standard_approval' AND d.verdict='approved' AND r.input_sha256=%s AND d.input_sha256=r.input_sha256",
        (p.org_id, revision, rev["content_sha256"]),
    ).first()
    if not approved:
        raise Denied("STANDARD_NOT_APPROVED")
    return rev


def configuration(c, p, purpose, ident=None):
    if ident is None:
        ident = c.exec_driver_sql(
            "SELECT id FROM ai_config_revisions WHERE org_id=%s AND config_key=%s ORDER BY version_no DESC LIMIT 1",
            (p.org_id, "research." + purpose + ".v2"),
        ).scalar_one_or_none()
    if not ident:
        raise Denied("MODEL_NOT_CONFIGURED")
    cfg = row(c, "ai_config_revisions", p.org_id, ident)
    conn = row(c, "provider_connections", p.org_id, cfg["provider_connection_id"])
    expected = {
        "model": "deepseek-flash",
        "parameters": parameters(purpose),
        "schema": output_schema(purpose),
    }
    if (
        not conn["enabled"]
        or conn["provider_code"] != "deepseek"
        or conn["secret_ref"] != "DEEPSEEK_KEY"
        or cfg["task_kind"] != "research." + purpose
        or cfg["model_identifier"] != expected["model"]
        or cfg["parameters"] != expected["parameters"]
        or cfg["output_schema"] != expected["schema"]
        or cfg["content_sha256"] != digest(expected)
    ):
        raise Denied("MODEL_NOT_CONFIGURED")
    return cfg, conn


def sample(c, p, frozen, *, raw_inputs=()):
    from app.processing.research import parse_text
    from app.research.predictions import exposure

    az = Authorizer(c, p)
    segments = []
    seen_sources = set()
    kinds = []
    missing = ["完整音视频与可靠时间点", "未提供的其他集数与结局", "独立校准及完整发布条件"]
    raw_by_version = {
        UUID(item["role"].split(":", 1)[1]): item["raw_asset_id"]
        for item in raw_inputs
        if item.get("raw_asset_id") and item["role"].startswith("parsed:")
    }
    for item in frozen["items"]:
        v = az.read("artifact_versions", item["artifact_version_id"])
        kinds.append(v["material_kind"])
        text = v["body_text"]
        source_kind = "material_version"
        source_id = v["id"]
        source_version = v["version_no"]
        if text is None:
            rid = raw_by_version.get(v["id"])
            if not rid:
                raise Denied("INSUFFICIENT_MATERIAL")
            raw = az.read("raw_assets", rid)
            if raw["parent_artifact_version_id"] != v["id"] or raw["asset_kind"] != "text":
                raise Denied("VALIDATION_FAILED")
            text = raw["body_text"]
            source_kind = "parsed_document"
            source_id = raw["id"]
            source_version = 1
        if (source_kind, source_id) in seen_sources:
            continue
        seen_sources.add((source_kind, source_id))
        for para in parse_text(text):
            if len(para["text"]) > 12000 or len(segments) >= 50:
                raise Denied("INSUFFICIENT_MATERIAL")
            segments.append(
                {
                    "id": "s" + str(len(segments) + 1),
                    "source_kind": source_kind,
                    "source_id": str(source_id),
                    "source_version": source_version,
                    "text": para["text"],
                }
            )
    _context, seen = exposure(c, p, frozen["id"])
    value = {
        "business_code": frozen["business_code"],
        "scope": "synopsis"
        if all(k == "reference" for k in kinds)
        else "episode"
        if frozen["scope"] == "unit"
        else "material",
        "outcome_exposure": seen,
        "segments": segments,
        "missing_inputs": missing,
    }
    from app.ai.research import ResearchInput

    return ResearchInput.model_validate(value).model_dump(mode="json")


def parsed_inputs(c, p, frozen):
    az = Authorizer(c, p)
    out = []
    for version, source in sorted(frozen.get("parsed_sources", {}).items()):
        raw = az.read("raw_assets", UUID(source["raw_asset_id"]))
        if raw["sha256"] != source["sha256"] or raw["parent_artifact_version_id"] != UUID(version):
            raise Denied("INSUFFICIENT_MATERIAL")
        out.append({"role": "parsed:" + version, "raw_asset_id": raw["id"]})
    return out


def start_analysis(c, p, key, request, handler=None):
    refresh(c, p)
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    frozen = read_input(c, p, request.input_set_id, "research.submit")
    if frozen["business_code"] != "motion_comic":
        raise Denied("INSUFFICIENT_MATERIAL")
    if not request.execute_now:
        # Input sets are drafts already; do not create an unauthorized billable queued task.
        raise Denied("ACCESS_DENIED")
    az.require("works", frozen["work_id"], "research.run")
    if request.max_external_calls != 1:
        raise Denied("BUDGET_EXHAUSTED")
    purpose = request.purpose
    standard = approved_standard(
        c,
        p,
        "analysis_template" if purpose == "decompose" else "rubric",
        business=frozen["business_code"],
    )
    cfg, _conn = configuration(c, p, purpose)
    from app.research.analysis_task import Analyze

    processor = handler or Analyze(purpose)

    def perform():
        tid = uuid4()
        manifest = [
            {"role": "materials", "input_set_id": frozen["id"]},
            {"role": "config", "ai_config_revision_id": cfg["id"]},
            {
                "role": "template" if purpose == "decompose" else "rubric",
                "standard_revision_id": standard["id"],
            },
            *parsed_inputs(c, p, frozen),
        ]
        values = {
            "id": tid,
            "org_id": p.org_id,
            "kind": "research." + purpose,
            "handler_version": "2",
            "work_id": frozen["work_id"],
            "business_code": frozen["business_code"],
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_external_calls": 1,
            "max_attempts": 1,
            "idempotency_key": str(key),
        }
        values["input_sha256"] = input_digest(
            values, processor.freeze(c, values, az, inputs=manifest)
        )
        create_task(c, values, manifest)
        if purpose == "decompose":
            work = az.require("works", frozen["work_id"], "research.submit")
            generation = work["report_generation"] + 1
            compare_and_swap(
                c,
                "works",
                p.org_id,
                work["id"],
                work["lock_version"],
                {"report_generation": generation},
            )
            insert(
                c,
                "analysis_runs",
                p.org_id,
                report_generation=generation,
                input_set_id=frozen["id"],
                task_id=tid,
                template_revision_id=standard["id"],
                ai_config_revision_id=cfg["id"],
            )
        audit(c, p.org_id, p.member_id, "research.analysis_submitted", "task", tid)
        return {"id": str(tid), "kind": "task", "state": "queued", "execute_now": True}

    saved = receipt(c, p, "startAnalysis", key, request.model_dump(mode="json"), perform)
    # Current source/config/standard permission is required on replay, too.
    processor.freeze(c, row(c, "tasks", p.org_id, UUID(saved["id"])), az)
    return {**saved, "id": UUID(saved["id"])}


def read_report(c, p, ident):
    refresh(c, p)
    report = Authorizer(c, p).read("analysis_reports", ident)
    refs = []
    for ref in c.exec_driver_sql(
        "SELECT claim_path,evidence_id FROM report_evidence WHERE org_id=%s AND report_id=%s ORDER BY claim_path,evidence_id",
        (p.org_id, ident),
    ).mappings():
        evidence = Authorizer(c, p).read("evidence_refs", ref["evidence_id"])
        target_version = evidence["artifact_version_id"]
        if target_version is None:
            target_version = Authorizer(c, p).read("raw_assets", evidence["raw_asset_id"])[
                "parent_artifact_version_id"
            ]
        episode = None
        if target_version:
            Authorizer(c, p).read("artifact_versions", target_version)
            episode = c.exec_driver_sql(
                "SELECT episode_no_at_input FROM artifact_version_units WHERE org_id=%s AND artifact_version_id=%s ORDER BY unit_id LIMIT 1",
                (p.org_id, target_version),
            ).scalar_one_or_none()
        refs.append(
            {
                **dict(ref),
                "target_artifact_version_id": target_version,
                "target_episode_no": episode,
                **{
                    k: evidence[k]
                    for k in ("raw_asset_id", "artifact_version_id", "paragraph_no", "quoted_text")
                },
            }
        )
    return {**report, "evidence": refs}


def read_evaluation(c, p, ident):
    refresh(c, p)
    value = Authorizer(c, p).read("quality_evaluations", ident)
    for eid in c.exec_driver_sql(
        "SELECT evidence_id FROM evaluation_evidence WHERE org_id=%s AND evaluation_id=%s",
        (p.org_id, ident),
    ).scalars():
        Authorizer(c, p).read("evidence_refs", eid)
    return value


def project(schema, value):
    """Public read views expose the contract fields, never internal execution/file keys."""
    return schema.model_validate({k: v for k, v in value.items() if k in schema.model_fields})


def history(c, p, work_id):
    from app.contracts.models import Evaluation, FrozenPrediction
    from app.research.analysis_contracts import AnalysisHistory, PredictionAssessment, ReportView
    from app.research.prediction_contracts import DraftView
    from app.research.predictions import read_draft, read_prediction

    refresh(c, p)
    Authorizer(c, p).require("works", work_id, "content.read")
    reports = [
        project(ReportView, read_report(c, p, r))
        for r in c.exec_driver_sql(
            "SELECT id FROM analysis_reports WHERE org_id=%s AND work_id=%s ORDER BY version_no DESC",
            (p.org_id, work_id),
        ).scalars()
    ]
    evaluations = [
        project(Evaluation, read_evaluation(c, p, r))
        for r in c.exec_driver_sql(
            "SELECT e.id FROM quality_evaluations e JOIN input_sets i ON i.org_id=e.org_id AND i.id=e.input_set_id WHERE e.org_id=%s AND i.work_id=%s ORDER BY e.created_at DESC,e.id DESC",
            (p.org_id, work_id),
        ).scalars()
    ]
    drafts = [
        project(DraftView, read_draft(c, p, r))
        for r in c.exec_driver_sql(
            "SELECT d.id FROM prediction_drafts d JOIN input_sets i ON i.org_id=d.org_id AND i.id=d.input_set_id WHERE d.org_id=%s AND i.work_id=%s ORDER BY d.created_at DESC,d.id DESC",
            (p.org_id, work_id),
        ).scalars()
    ]
    frozen = [
        project(FrozenPrediction, read_prediction(c, p, r))
        for r in c.exec_driver_sql(
            "SELECT d.id FROM predictions d JOIN input_sets i ON i.org_id=d.org_id AND i.id=d.input_set_id WHERE d.org_id=%s AND i.work_id=%s ORDER BY d.frozen_at DESC,d.id DESC",
            (p.org_id, work_id),
        ).scalars()
    ]
    assessments = []
    for r in c.exec_driver_sql(
        "SELECT t.id AS task_id,o.raw_asset_id,i.input_set_id FROM tasks t JOIN task_outputs o ON o.org_id=t.org_id AND o.task_id=t.id AND o.role='prediction_assessment' JOIN task_inputs i ON i.org_id=t.org_id AND i.task_id=t.id AND i.input_set_id IS NOT NULL WHERE t.org_id=%s AND t.work_id=%s AND t.state='succeeded' ORDER BY t.created_at DESC,t.id DESC",
        (p.org_id, work_id),
    ).mappings():
        read_input(c, p, r["input_set_id"])
        raw = Authorizer(c, p).read("raw_assets", r["raw_asset_id"])
        if hashlib.sha256(raw["body_text"].encode()).hexdigest() != raw["sha256"]:
            raise Denied("INSUFFICIENT_MATERIAL")
        body = json.loads(raw["body_text"])
        assessments.append(
            PredictionAssessment(
                task_id=r["task_id"],
                raw_id=raw["id"],
                input_set_id=r["input_set_id"],
                result_state=body["result_state"],
                uncertainty_note=body["uncertainty_note"],
                limitations=body["limitations"],
                created_at=raw["created_at"],
            )
        )
    return AnalysisHistory(
        reports=reports,
        evaluations=evaluations,
        prediction_drafts=drafts,
        frozen_predictions=frozen,
        prediction_assessments=assessments,
    ).model_dump(mode="json")
