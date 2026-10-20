"""Same-origin research APIs; service commits precede queue publication."""

from fastapi.responses import JSONResponse

from app.contracts.api import OPERATIONS, add_operation
from app.contracts.models import Envelope
from app.research.service import (
    add_material,
    create_work,
    detail,
    direct_intake,
    intelligence_intake,
    list_works,
)
from app.security.http import preflight
from app.security.sessions import authenticate

NAMES = {
    "listWorks",
    "createInputSet",
    "getInputSet",
    "startAnalysis",
    "getReport",
    "getEvaluation",
    "getAnalysisHistory",
    "createPredictionDraft",
    "getPredictionDraft",
    "updatePredictionDraft",
    "freezePrediction",
    "getPrediction",
    "retractPrediction",
    "getWork",
    "createWork",
    "submitIntelligence",
    "createResearchMaterial",
    "submitDirectResearch",
}


def dispatch(
    *,
    request,
    engine,
    session=None,
    filters=None,
    body=None,
    work_id=None,
    input_set_id=None,
    report_id=None,
    evaluation_id=None,
    draft_id=None,
    prediction_id=None,
    idempotency_key=None,
    csrf_token=None,
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    with engine.begin() as c:
        p = authenticate(c, session)
        if spec.name == "listWorks":
            data = list_works(c, p, filters)
        elif spec.name == "getWork":
            data = detail(c, p, work_id)
        elif spec.name == "createWork":
            data = create_work(c, p, idempotency_key, body)
        elif spec.name == "submitIntelligence":
            data = intelligence_intake(c, p, idempotency_key, body)
        elif spec.name == "submitDirectResearch":
            data = direct_intake(c, p, idempotency_key, body)
        elif spec.name == "createResearchMaterial":
            data = add_material(c, p, idempotency_key, work_id, body)
        else:
            from app.research import analysis, inputs, predictions
            from app.research.analysis import project

            action = spec.name
            if action == "createInputSet":
                data = inputs.create_input(c, p, idempotency_key, body)
            elif action == "getInputSet":
                data = inputs.read_input(c, p, input_set_id)
            elif action == "startAnalysis":
                data = analysis.start_analysis(c, p, idempotency_key, body)
            elif action == "getReport":
                data = analysis.read_report(c, p, report_id)
            elif action == "getEvaluation":
                data = analysis.read_evaluation(c, p, evaluation_id)
            elif action == "getAnalysisHistory":
                data = analysis.history(c, p, work_id)
            elif action == "createPredictionDraft":
                data = predictions.create_draft(c, p, idempotency_key, body)
            elif action == "getPredictionDraft":
                data = predictions.read_draft(c, p, draft_id)
            elif action == "updatePredictionDraft":
                data = predictions.update_draft(c, p, idempotency_key, draft_id, body)
            elif action == "freezePrediction":
                data = predictions.freeze_prediction(
                    c, p, idempotency_key, draft_id, body.expected_lock_version
                )
            elif action == "retractPrediction":
                data = predictions.retract_prediction(
                    c, p, idempotency_key, prediction_id, body.reason
                )
            else:
                data = predictions.read_prediction(c, p, prediction_id)
            data = project(spec.response, data).model_dump(mode="json")
    if spec.name == "freezePrediction":
        from uuid import UUID

        from app.research.analysis import project
        from app.research.predictions import confirm_prediction

        with engine.begin() as c:
            p = authenticate(c, session)
            data = project(spec.response, confirm_prediction(c, p, UUID(data["id"]))).model_dump(
                mode="json"
            )
    elif spec.name == "startAnalysis":
        from app.research.worker import dispatch_analysis

        dispatch_analysis(p.org_id, data["id"])
    if spec.name in ("submitIntelligence", "submitDirectResearch", "createResearchMaterial"):
        from app.research.worker import dispatch_parse

        dispatch_parse(p.org_id, data["task_id"])
    payload = Envelope[spec.response](request_id=request.state.request_id, data=data)
    return JSONResponse(
        payload.model_dump(mode="json"),
        status_code=spec.status,
        headers={"X-Request-ID": str(payload.request_id), "Cache-Control": "no-store"},
    )


def mount(app):
    for spec in OPERATIONS:
        if spec.name in NAMES:
            add_operation(spec, app, dispatch, preflight)
