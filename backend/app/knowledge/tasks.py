"""One-call extraction/review; immutable targets, formal comparison snapshots and head fences."""

import hashlib
import json
from uuid import UUID, uuid4

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import create_task
from app.intelligence.service import row
from app.knowledge import reviews, service
from app.knowledge.model import KnowledgeModel, output_schema, parameters, validate_output
from app.research.analysis import approved_standard
from app.research.analysis_task import Analyze
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.storage import audit, lock_org, receipt
from app.tasks.service import TaskError, input_digest


def configuration(c, p, purpose, ident=None):
    if ident is None:
        ident = c.exec_driver_sql(
            "SELECT id FROM ai_config_revisions WHERE org_id=%s AND config_key=%s ORDER BY version_no DESC LIMIT 1",
            (p.org_id, "knowledge." + purpose + ".v2"),
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
        or cfg["config_key"] != "knowledge." + purpose + ".v2"
        or cfg["task_kind"] != "knowledge." + purpose
        or cfg["model_identifier"] != "deepseek-flash"
        or cfg["parameters"] != expected["parameters"]
        or cfg["output_schema"] != expected["schema"]
        or cfg["content_sha256"] != digest(expected)
        or not cfg["prompt_revision_id"]
    ):
        raise Denied("MODEL_NOT_CONFIGURED")
    return cfg, conn


def snapshot(c, p, purpose, r, v, comparisons):
    az = Authorizer(c, p)
    refs = list(
        c.exec_driver_sql(
            "SELECT DISTINCT evidence_id FROM "
            + (
                "knowledge_evidence WHERE org_id=%s AND revision_id=%s"
                if r["purpose"] == "knowledge_release"
                else "report_evidence WHERE org_id=%s AND report_id=%s"
            )
            + " ORDER BY evidence_id",
            (p.org_id, v["id"]),
        ).scalars()
    )
    segments = []
    evidence = {}
    provenance = {}
    kinds = []
    for eid in refs:
        e = az.read("evidence_refs", eid)
        if not e["quoted_text"] or len(e["quoted_text"]) > 12000:
            raise Denied("INSUFFICIENT_MATERIAL")
        sid = "e" + str(len(segments) + 1)
        evidence[sid] = str(eid)
        source = (
            az.read("artifact_versions", e["artifact_version_id"])
            if e["artifact_version_id"]
            else az.read("raw_assets", e["raw_asset_id"])
        )
        parent = (
            az.read("artifact_versions", source["parent_artifact_version_id"])
            if source.get("parent_artifact_version_id")
            else source
        )
        provenance[sid] = {
            "origin": source.get("origin", "material_version"),
            "independently_verified": False,
        }
        kinds.append(parent.get("material_kind", "reference"))
        segments.append(
            {
                "id": sid,
                "source_kind": "material_version"
                if e["artifact_version_id"]
                else "parsed_document",
                "source_id": str(source["id"]),
                "source_version": source.get("version_no", 1),
                "text": e["quoted_text"],
            }
        )
    if not segments or len(segments) > 50:
        raise Denied("INSUFFICIENT_MATERIAL")
    business = (
        service.read_candidate(c, p, v["id"])["business_codes"]
        if r["purpose"] == "knowledge_release"
        else [az.read("works", v["work_id"])["business_code"]]
    )
    if business != ["motion_comic"]:
        raise Denied("SERVICE_NOT_READY")
    compare = []
    for rid in comparisons:
        item = az.read("knowledge_revisions", rid)
        compare.append(
            {
                "id": str(rid),
                "version": item["version_no"],
                "sha256": item["content_sha256"],
                "title": item["title"],
                "body": item["body_text"],
                "limitations": item["limitations"],
            }
        )
    return {
        "business_code": "motion_comic",
        "scope": "synopsis" if all(x == "reference" for x in kinds) else "material",
        "outcome_exposure": "unknown",
        "segments": segments,
        "missing_inputs": ["只有当前引用的局部资料", "对照仅限当前授权业务正式知识"],
        "target_revision": {
            "id": str(v["id"]),
            "version": v["version_no"],
            "sha256": v["content_sha256"],
        },
        "target": {
            "title": v.get("title"),
            "body": v.get("body_text", v.get("body")),
            "limitations": v.get("limitations"),
            "tags": v.get("tags", []),
            "business_codes": business,
        },
        "comparisons": compare,
        "comparison_complete": True,
        "comparison_scope": "当前授权AI漫剧正式版本，非全库无冲突证明",
        "source_provenance": provenance,
    }, evidence


class KnowledgeTask(Analyze):
    def __init__(self, purpose, model=None, store=None):
        if purpose not in ("extract", "review"):
            raise ValueError("Unknown knowledge purpose")
        self.purpose = purpose
        self.model = model or KnowledgeModel()
        self.store = store
        self.action = "research.run" if purpose == "extract" else "knowledge.review.run"

    def freeze(self, c, task, az, *, inputs=None):
        inputs = (
            list(inputs)
            if inputs is not None
            else list(
                c.exec_driver_sql(
                    "SELECT * FROM task_inputs WHERE org_id=%s AND task_id=%s ORDER BY position",
                    (task["org_id"], task["id"]),
                ).mappings()
            )
        )
        if (
            task["kind"] != "knowledge." + self.purpose
            or task["handler_version"] != "2"
            or task["max_external_calls"] != 1
            or task["max_attempts"] != 1
        ):
            raise TaskError("INVALID_INPUT")
        target = next((i for i in inputs if i.get("review_request_id")), None)
        config = next((i for i in inputs if i.get("ai_config_revision_id")), None)
        if (
            not target
            or not config
            or len(inputs) != 2 + sum(bool(i.get("knowledge_revision_id")) for i in inputs)
        ):
            raise TaskError("INVALID_INPUT")
        r, v = reviews.access(c, az.p, target["review_request_id"])
        action = (
            "knowledge.review.run" if r["purpose"] == "knowledge_release" else "report.review.run"
        )
        if self.purpose == "extract":
            if r["purpose"] != "report_review":
                raise TaskError("INVALID_INPUT")
            az.require("analysis_reports", v["id"], "research.run")
            if not az.allowed("knowledge.edit", az.scopes("analysis_reports", v)):
                raise Denied("ACCESS_DENIED")
        else:
            if r["purpose"] not in ("knowledge_release", "report_review"):
                raise TaskError("INVALID_INPUT")
            reviews.target(c, az.p, r["purpose"], v["id"], action)
            reviews.immutable(c, az.p, r, v)
            old = reviews.heads(c, az.p, r["id"]).get("ai", {})
            expected = (
                "review:"
                + str(old.get("decision_id", "none"))
                + ":"
                + str(old.get("lock_version", 0))
            )
            if target["role"] != expected:
                raise TaskError("INVALID_INPUT")
        cfg, conn = configuration(c, az.p, self.purpose, config["ai_config_revision_id"])
        sample, mapping = snapshot(
            c,
            az.p,
            self.purpose,
            r,
            v,
            [i["knowledge_revision_id"] for i in inputs if i.get("knowledge_revision_id")],
        )
        standard = approved_standard(
            c, az.p, "prompt", cfg["prompt_revision_id"], sample["business_code"]
        )
        sample["standard"] = standard["definition"]
        return {
            "sample": sample,
            "evidence": mapping,
            "request_id": str(r["id"]),
            "target_id": str(v["id"]),
            "target_sha256": v["content_sha256"],
            "config_id": str(cfg["id"]),
            "config_sha256": cfg["content_sha256"],
            "standard_id": str(standard["id"]),
            "standard_sha256": standard["content_sha256"],
            "connection_version": conn["lock_version"],
            "expected_ai_role": target["role"],
        }

    def publish(self, c, task, result):
        from app.security.sessions import MemberPrincipal
        from app.storage.http import get_store

        p = MemberPrincipal(task["org_id"], task["execution_authorized_by"])
        frozen = self.freeze(c, task, Authorizer(c, p))
        ex = row(c, "ai_executions", p.org_id, UUID(result["execution_id"]))
        if (
            ex["task_id"] != task["id"]
            or ex["config_revision_id"] != UUID(frozen["config_id"])
            or ex["result_state"] not in ("completed", "insufficient_evidence")
        ):
            raise TaskError("INVALID_INPUT")
        saved = row(c, "file_objects", p.org_id, ex["output_file_id"])
        store = self.store or get_store()
        with store.open(p.org_id, ex["output_file_id"]) as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != saved["sha256"]:
            raise TaskError("INVALID_INPUT")
        checked = validate_output(self.purpose, frozen["sample"], json.loads(raw))
        out = checked["output"]

        def output(position, role, **values):
            c.execute(
                metadata.tables["task_outputs"]
                .insert()
                .values(org_id=p.org_id, task_id=task["id"], position=position, role=role, **values)
            )

        output(0, "model_execution", ai_execution_id=ex["id"])
        if self.purpose == "review" and out["result_state"] == "completed":
            r, _ = reviews.access(c, p, UUID(frozen["request_id"]))
            hh = reviews.heads(c, p, r["id"]).get("ai", {})
            did = reviews.append_decision(
                c,
                p,
                r,
                "ai",
                "approved" if out["decision"] == "approved" else "rejected",
                (
                    "；".join(x["kind"] + "：" + x["reason"][:120] for x in out["checks"])
                    + "；"
                    + "；".join(out["limitations"])
                )[:1000],
                execution=ex["id"],
                expected_id=hh.get("decision_id"),
                expected_version=hh.get("lock_version"),
            )
            output(1, "ai_review", review_decision_id=did)
        elif self.purpose == "extract":
            from app.contracts.models import KnowledgeCreate

            claims = {x["key"]: x for x in out["claims"]}
            for i, item in enumerate(out["candidates"], 1):
                refs = {
                    UUID(frozen["evidence"][e["segment_id"]])
                    for key in item["claim_keys"]
                    for e in claims[key]["evidence"]
                }
                candidate = KnowledgeCreate(
                    title=item["title"],
                    body_text=item["body"],
                    knowledge_type=item["knowledge_type"],
                    browse_category=item["browse_category"],
                    business_codes=["motion_comic"],
                    tags=[{"kind": "stage", "code": "script"}],
                    evidence_ids=sorted(refs),
                    source_report_id=UUID(frozen["target_id"]),
                    limitations=item["limitations"]
                    + "；适用范围："
                    + "；".join(item["applicability"]),
                )
                kid = insert(
                    c,
                    "knowledge_items",
                    p.org_id,
                    title=candidate.title,
                    owner_member_id=p.member_id,
                    created_by=p.member_id,
                )
                rid = service.add_revision(c, p, kid, candidate, 1)
                from app.core.repository import compare_and_swap

                compare_and_swap(
                    c, "knowledge_items", p.org_id, kid, 1, {"current_revision_id": rid}
                )
                output(i, "candidate", knowledge_revision_id=rid)
        audit(
            c, p.org_id, p.member_id, "knowledge." + self.purpose + "_completed", "task", task["id"]
        )

    def after_finish(self, c, task, result):
        pass


def start_task(c, p, key, purpose, r, v):
    proc = KnowledgeTask(purpose)
    cfg, _ = configuration(c, p, purpose)
    comparisons = []
    if purpose == "review":
        comparisons = [
            x["revision_id"]
            for x in service.listing(c, p, "motion_comic")["items"]
            if x["revision_id"] != v["id"]
        ]
    if len(comparisons) > 100:
        raise Denied("INSUFFICIENT_MATERIAL")
    old = reviews.heads(c, p, r["id"]).get("ai", {})
    manifest = [
        {
            "review_request_id": r["id"],
            "role": "review:"
            + str(old.get("decision_id", "none"))
            + ":"
            + str(old.get("lock_version", 0)),
        },
        {"role": "config", "ai_config_revision_id": cfg["id"]},
        *[{"role": "comparison", "knowledge_revision_id": i} for i in comparisons],
    ]
    tid = uuid4()
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "knowledge." + purpose,
        "handler_version": "2",
        "business_code": "motion_comic",
        "work_id": v.get("work_id"),
        "knowledge_id": v.get("knowledge_id"),
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "idempotency_key": str(key),
        "max_attempts": 1,
        "max_external_calls": 1,
    }
    values["input_sha256"] = input_digest(
        values, proc.freeze(c, values, Authorizer(c, p), inputs=manifest)
    )
    create_task(c, values, manifest)
    return tid


def start_review(c, p, key, r, v):
    return start_task(c, p, key, "review", r, v)


def start_extract(c, p, key, report_id, request):
    lock_org(c, p.org_id)
    az = Authorizer(c, p)
    v = az.require("analysis_reports", report_id, "research.run")
    if not az.allowed("knowledge.edit", az.scopes("analysis_reports", v)):
        raise Denied("ACCESS_DENIED")
    if not request.execute_now or request.max_external_calls != 1:
        raise Denied("VALIDATION_FAILED")

    def perform():
        rid = reviews.ensure_request(c, p, "report_review", report_id)
        r, _ = reviews.access(c, p, rid)
        tid = start_task(c, p, key, "extract", r, v)
        return {"id": str(tid)}

    saved = receipt(
        c,
        p,
        "extractKnowledge",
        key,
        {"report_id": str(report_id), **request.model_dump(mode="json")},
        perform,
    )
    task = row(c, "tasks", p.org_id, UUID(saved["id"]))
    KnowledgeTask("extract").freeze(c, task, az)
    return {"id": task["id"], "kind": "task", "state": task["state"], "execute_now": True}
