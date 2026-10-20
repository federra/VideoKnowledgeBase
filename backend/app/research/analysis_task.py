"""One-call research stages; frozen inputs, private raw responses and cited products."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from app.ai.deepseek import ModelError
from app.ai.feedback_task import private_file
from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import compare_and_swap
from app.intelligence.service import row
from app.research.analysis import approved_standard, configuration, sample
from app.research.inputs import read_input
from app.research.stage_model import StageModel, validate_output
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import MemberPrincipal
from app.security.storage import lock_org
from app.tasks.service import TaskError


class Analyze:
    action = "research.run"

    def __init__(self, purpose, model=None, store=None):
        if purpose not in ("decompose", "evaluate", "predict"):
            raise ValueError("Unknown purpose")
        self.purpose = purpose
        self.model = model or StageModel()
        self.store = store

    def freeze(self, c, task, az, *, inputs=None):
        inputs = (
            inputs
            if inputs is not None
            else c.exec_driver_sql(
                "SELECT * FROM task_inputs WHERE org_id=%s AND task_id=%s ORDER BY position",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .all()
        )
        if (
            task["kind"] != "research." + self.purpose
            or task["handler_version"] != "2"
            or task["max_external_calls"] != 1
            or task["max_attempts"] != 1
        ):
            raise TaskError("INVALID_INPUT")
        material = next((i for i in inputs if i.get("input_set_id")), None)
        config = next((i for i in inputs if i.get("ai_config_revision_id")), None)
        standard = next((i for i in inputs if i.get("standard_revision_id")), None)
        if (
            not material
            or not config
            or not standard
            or len(inputs) != 3 + sum(bool(i.get("raw_asset_id")) for i in inputs)
        ):
            raise TaskError("INVALID_INPUT")
        frozen = read_input(c, az.p, material["input_set_id"], "research.submit")
        az.require("works", frozen["work_id"], self.action)
        if task["work_id"] != frozen["work_id"] or task["business_code"] != frozen["business_code"]:
            raise TaskError("INVALID_INPUT")
        kind = "analysis_template" if self.purpose == "decompose" else "rubric"
        rev = approved_standard(
            c, az.p, kind, standard["standard_revision_id"], business=frozen["business_code"]
        )
        cfg, conn = configuration(c, az.p, self.purpose, config["ai_config_revision_id"])
        value = sample(c, az.p, frozen, raw_inputs=inputs)
        value["template" if kind == "analysis_template" else "rubric"] = rev["definition"]
        # Locators stay internal; the AI sees only exact cited segments and approved definitions.
        from app.processing.research import parse_text

        offsets = {}
        locators = {}
        for segment in value["segments"]:
            sid = UUID(segment["source_id"])
            raw = segment["source_kind"] == "parsed_document"
            target = az.read("raw_assets" if raw else "artifact_versions", sid)
            position = offsets.get(sid, 0)
            paragraph = parse_text(target["body_text"])[position]
            offsets[sid] = position + 1
            locators[segment["id"]] = {
                "raw_asset_id": sid if raw else None,
                "artifact_version_id": None if raw else sid,
                "paragraph_no": paragraph["number"],
            }
        return {
            "sample": value,
            "locators": {
                k: {n: str(v) if isinstance(v, UUID) else v for n, v in loc.items()}
                for k, loc in locators.items()
            },
            "input_set_id": str(frozen["id"]),
            "input_sha256": frozen["manifest_sha256"],
            "config_id": str(cfg["id"]),
            "config_sha256": cfg["content_sha256"],
            "standard_id": str(rev["id"]),
            "standard_sha256": rev["content_sha256"],
            "connection_version": conn["lock_version"],
        }

    def execute_ticket(self, runner, ticket, checkpoint):
        from app.storage.http import get_store

        store = self.store or get_store()
        execution = None

        def reserve(manifest):
            nonlocal execution
            with runner.engine.begin() as c:
                task = runner.live(c, ticket)
                if not task:
                    raise TaskError("ACCESS_REVOKED")
                runner.validate(c, task)
                fid = private_file(
                    c, store, task, json.dumps(manifest, ensure_ascii=False, sort_keys=True)
                )
                execution = insert(
                    c,
                    "ai_executions",
                    ticket.org,
                    task_id=ticket.task,
                    attempt_id=ticket.attempt,
                    config_revision_id=UUID(ticket.payload["config_id"]),
                    invocation_no=1,
                    input_sha256=manifest["input_sha256"],
                    input_manifest_file_id=fid,
                )
            store.forget(fid)

        checkpoint()
        try:
            reply = self.model.stage(self.purpose, ticket.payload["sample"], reserve=reserve)
        except ModelError as exc:
            if execution:
                with runner.engine.begin() as c:
                    lock_org(c, ticket.org)
                    task = row(c, "tasks", ticket.org, ticket.task)
                    fid = (
                        private_file(c, store, task, exc.raw_text)
                        if exc.raw_text is not None
                        else None
                    )
                    c.execute(
                        metadata.tables["ai_executions"]
                        .update()
                        .where(metadata.tables["ai_executions"].c.id == execution)
                        .values(
                            result_state="failed",
                            safe_error_code=str(exc),
                            finished_at=datetime.now(UTC),
                            output_file_id=fid,
                            provider_request_id=exc.provider_request_id,
                            input_tokens=exc.input_tokens,
                            output_tokens=exc.output_tokens,
                        )
                    )
                if fid:
                    store.forget(fid)
            raise TaskError(str(exc)) from None
        if execution is None:
            raise TaskError("INVALID_RESPONSE")
        with runner.engine.begin() as c:
            lock_org(c, ticket.org)
            task = row(c, "tasks", ticket.org, ticket.task)
            fid = private_file(c, store, task, reply.raw_text)
            c.execute(
                metadata.tables["ai_executions"]
                .update()
                .where(metadata.tables["ai_executions"].c.id == execution)
                .values(
                    result_state=reply.validated["output"]["result_state"],
                    output_file_id=fid,
                    provider_request_id=reply.provider_request_id,
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    finished_at=datetime.now(UTC),
                )
            )
        store.forget(fid)
        checkpoint()
        return {
            "execution_id": str(execution),
            "business_outcome": reply.validated["output"]["result_state"],
        }

    def publish(self, c, task, result):
        from app.storage.http import get_store

        p = MemberPrincipal(task["org_id"], task["execution_authorized_by"])
        az = Authorizer(c, p)
        frozen = self.freeze(c, task, az)
        execution = row(c, "ai_executions", task["org_id"], UUID(result["execution_id"]))
        if (
            execution["task_id"] != task["id"]
            or execution["config_revision_id"] != UUID(frozen["config_id"])
            or execution["result_state"] not in ("completed", "insufficient_evidence")
        ):
            raise TaskError("INVALID_INPUT")
        saved = row(c, "file_objects", task["org_id"], execution["output_file_id"])
        store = self.store or get_store()
        with store.open(task["org_id"], execution["output_file_id"]) as stream:
            body = stream.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024 or hashlib.sha256(body).hexdigest() != saved["sha256"]:
            raise TaskError("INVALID_INPUT")
        try:
            checked = validate_output(self.purpose, frozen["sample"], json.loads(body))
        except (ValueError, TypeError):
            raise TaskError("INVALID_RESPONSE") from None
        output = checked["output"]
        if (
            output["result_state"] != execution["result_state"]
            or output["result_state"] != result["business_outcome"]
        ):
            raise TaskError("INVALID_INPUT")
        tid = task["id"]
        org = task["org_id"]
        input_id = UUID(frozen["input_set_id"])

        def task_output(position, role, **target):
            c.execute(
                metadata.tables["task_outputs"]
                .insert()
                .values(org_id=org, task_id=tid, position=position, role=role, **target)
            )

        task_output(0, "model_execution", ai_execution_id=execution["id"])
        product = None
        if self.purpose == "decompose" and output["claims"]:
            run = (
                c.exec_driver_sql(
                    "SELECT * FROM analysis_runs WHERE org_id=%s AND task_id=%s", (org, tid)
                )
                .mappings()
                .one()
            )
            version = c.exec_driver_sql(
                "SELECT COALESCE(max(version_no),0)+1 FROM analysis_reports WHERE org_id=%s AND work_id=%s",
                (org, task["work_id"]),
            ).scalar_one()
            product = insert(
                c,
                "analysis_reports",
                org,
                work_id=task["work_id"],
                input_set_id=input_id,
                analysis_run_id=run["id"],
                ai_execution_id=execution["id"],
                version_no=version,
                coverage_kind="partial",
                body=output,
                missing_inputs=[{"description": v} for v in frozen["sample"]["missing_inputs"]],
                result_state=output["result_state"],
                content_sha256=digest(output),
            )
            task_output(1, "partial_report", report_id=product)
        elif self.purpose == "evaluate":
            product = insert(
                c,
                "quality_evaluations",
                org,
                input_set_id=input_id,
                task_id=tid,
                rubric_revision_id=UUID(frozen["standard_id"]),
                ai_execution_id=execution["id"],
                result_state=output["result_state"],
                quality_grade=output["grade"],
                dimensions={
                    "items": output["dimensions"],
                    "claims": output["claims"],
                    "limitations": output["limitations"],
                },
                summary="；".join(output["limitations"]),
                content_sha256=digest(output),
            )
            task_output(1, "quality_evaluation", evaluation_id=product)
        elif self.purpose == "predict":
            # No metric/calibration means no lawful numeric draft. Persist a cited insufficiency assessment.
            first = next(iter(frozen["locators"].values()))
            parent = (
                UUID(first["artifact_version_id"])
                if first["artifact_version_id"]
                else row(c, "raw_assets", org, UUID(first["raw_asset_id"]))[
                    "parent_artifact_version_id"
                ]
            )
            text = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            raw = insert(
                c,
                "raw_assets",
                org,
                origin="processing",
                asset_kind="response",
                parent_artifact_version_id=parent,
                processing_task_id=tid,
                body_text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                captured_at=datetime.now(UTC),
            )
            task_output(1, "prediction_assessment", raw_asset_id=raw)
        if self.purpose in ("decompose", "evaluate") and product:
            for claim in output["claims"]:
                for citation in claim["evidence"]:
                    locator = frozen["locators"][citation["segment_id"]]
                    target = {
                        k: UUID(v) if v and k.endswith("_id") else v for k, v in locator.items()
                    }
                    eid = insert(
                        c,
                        "evidence_refs",
                        org,
                        **target,
                        locator_kind="paragraph",
                        quoted_text=citation["quote"],
                    )
                    if self.purpose == "decompose":
                        c.execute(
                            metadata.tables["report_evidence"]
                            .insert()
                            .values(
                                org_id=org,
                                report_id=product,
                                claim_path="claims." + claim["key"],
                                evidence_id=eid,
                            )
                        )
                    else:
                        c.execute(
                            metadata.tables["evaluation_evidence"]
                            .insert()
                            .values(
                                org_id=org,
                                evaluation_id=product,
                                dimension_code=claim["dimension"],
                                evidence_id=eid,
                            )
                        )
            if self.purpose == "decompose":
                cited = set()
                for claim in output["claims"]:
                    for ref in claim["evidence"]:
                        loc = frozen["locators"][ref["segment_id"]]
                        vid = (
                            UUID(loc["artifact_version_id"])
                            if loc["artifact_version_id"]
                            else row(c, "raw_assets", org, UUID(loc["raw_asset_id"]))[
                                "parent_artifact_version_id"
                            ]
                        )
                        cited.add(vid)
                units = {}
                for u in c.exec_driver_sql(
                    "SELECT i.work_id,i.artifact_version_id,u.unit_id,u.episode_no_at_input,u.unit_title_at_input FROM input_set_items i JOIN artifact_versions v ON v.org_id=i.org_id AND v.id=i.artifact_version_id JOIN artifact_version_units u ON u.org_id=v.org_id AND u.artifact_version_id=v.id WHERE i.org_id=%s AND i.input_set_id=%s AND i.role='primary' AND v.material_kind<>'reference' ORDER BY i.position",
                    (org, input_id),
                ).mappings():
                    supported = (
                        output["result_state"] == "completed" and u["artifact_version_id"] in cited
                    )
                    if u["unit_id"] not in units:
                        units[u["unit_id"]] = {
                            "org_id": org,
                            "report_id": product,
                            "work_id": u["work_id"],
                            "unit_id": u["unit_id"],
                            "coverage_state": "insufficient_evidence",
                            "episode_no_at_report": u["episode_no_at_input"],
                            "unit_title_at_report": u["unit_title_at_input"],
                        }
                    if supported:
                        units[u["unit_id"]]["coverage_state"] = "analyzed"
                for values in units.values():
                    c.execute(metadata.tables["report_units"].insert().values(**values))

            c.exec_driver_sql(
                "SELECT cip_seal(%s,%s,%s)",
                (
                    "analysis_reports" if self.purpose == "decompose" else "quality_evaluations",
                    org,
                    product,
                ),
            )

    def after_finish(self, c, task, result):
        if self.purpose != "decompose":
            return
        report = c.exec_driver_sql(
            "SELECT report_id FROM task_outputs WHERE org_id=%s AND task_id=%s AND report_id IS NOT NULL",
            (task["org_id"], task["id"]),
        ).scalar_one_or_none()
        if not report:
            return
        run = (
            c.exec_driver_sql(
                "SELECT report_generation,input_set_id FROM analysis_runs WHERE org_id=%s AND task_id=%s",
                (task["org_id"], task["id"]),
            )
            .mappings()
            .one()
        )
        work = row(c, "works", task["org_id"], task["work_id"])
        current = c.exec_driver_sql(
            "SELECT NOT EXISTS(SELECT 1 FROM input_set_items i JOIN artifact_versions v ON v.org_id=i.org_id AND v.id=i.artifact_version_id JOIN artifacts a ON a.org_id=v.org_id AND a.id=v.artifact_id WHERE i.org_id=%s AND i.input_set_id=%s AND i.role='primary' AND a.current_version_id<>v.id)",
            (task["org_id"], run["input_set_id"]),
        ).scalar_one()
        if current and run["report_generation"] == work["report_generation"]:
            compare_and_swap(
                c,
                "works",
                task["org_id"],
                work["id"],
                work["lock_version"],
                {"latest_report_id": report},
            )
