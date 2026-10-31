from fastapi.responses import JSONResponse

from app.contracts.api import Operation, add_operation
from app.contracts.models import Envelope
from app.security.http import preflight
from app.security.sessions import authenticate
from app.topics import scoring
from app.topics.score_contracts import EvaluateRequest, ScoreTaskView

OPERATIONS = [
    Operation(
        "POST",
        "/topics/{topic_id}/evaluate",
        "evaluateTopic",
        ScoreTaskView,
        ("content.write",),
        "S08.2",
        request=EvaluateRequest,
        status=202,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/topics/evaluations/{evaluation_id}",
        "getTopicEvaluation",
        ScoreTaskView,
        ("content.read",),
        "S08.2",
        implementation="implemented",
    ),
]


def dispatch(
    *,
    request,
    engine,
    session=None,
    body=None,
    topic_id=None,
    evaluation_id=None,
    idempotency_key=None,
    csrf_token=None,
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    with engine.begin() as c:
        p = authenticate(c, session)
        if spec.name == "evaluateTopic":
            data = scoring.start(c, p, str(idempotency_key), topic_id, body)
        else:
            data = scoring.read(c, p, evaluation_id)
    if spec.name == "evaluateTopic" and data["state"] == "queued":
        from app.topics.score_worker import dispatch_score

        dispatch_score(p.org_id, data["id"])
    payload = Envelope[spec.response](request_id=request.state.request_id, data=data)
    return JSONResponse(
        payload.model_dump(mode="json"),
        status_code=spec.status,
        headers={"Cache-Control": "no-store", "X-Request-ID": str(request.state.request_id)},
    )


def mount(app):
    for spec in OPERATIONS:
        add_operation(spec, app, dispatch, preflight)
