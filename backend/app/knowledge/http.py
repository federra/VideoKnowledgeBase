"""Knowledge endpoints reuse authenticated same-origin preflight and safe schemas."""

from fastapi.responses import JSONResponse

from app.collection.paging import page
from app.contracts.api import OPERATIONS, add_operation
from app.contracts.models import Envelope
from app.knowledge import reviews, service
from app.research.analysis import project
from app.security.errors import Denied
from app.security.http import preflight
from app.security.sessions import authenticate

NAMES = {
    "getKnowledgeSources",
    "searchKnowledge",
    "listKnowledgeCandidates",
    "getKnowledgeCandidate",
    "createKnowledge",
    "getPublishedKnowledge",
    "reviseKnowledge",
    "getCandidateRevision",
    "requestReview",
    "getReview",
    "submitHumanDecision",
    "publishKnowledge",
    "approveKnowledgePublication",
    "extractKnowledge",
}


def filter_scope(name, filters):
    from app.security.primitives import digest

    return name + ":" + digest(filters.model_dump(mode="json", exclude={"cursor"}))


def dispatch(
    *,
    request,
    engine,
    session=None,
    filters=None,
    body=None,
    knowledge_id=None,
    revision_id=None,
    request_id=None,
    report_id=None,
    idempotency_key=None,
    csrf_token=None,
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    name = spec.name
    with engine.begin() as c:
        p = authenticate(c, session)
        if name in ("searchKnowledge", "listKnowledgeCandidates"):
            if filters.mode != "keyword":
                raise Denied("SERVICE_NOT_READY")
            data = service.listing(
                c,
                p,
                filters.business_code,
                candidate=name == "listKnowledgeCandidates",
                q=filters.q,
                category=filters.browse_category,
                source_report_id=filters.source_report_id,
            )
            if filters.tag:
                kind, code = filters.tag.split(":", 1)
                data["items"] = [
                    x for x in data["items"] if {"kind": kind, "code": code} in x["tags"]
                ]
            data["items"] = [
                project(spec.response.model_fields["items"].annotation.__args__[0], x).model_dump(
                    mode="json"
                )
                for x in data["items"]
            ]
            data = page(
                c,
                p,
                data,
                kind=filter_scope(name, filters),
                business=filters.business_code,
                limit=filters.limit,
                cursor=filters.cursor,
            )
        elif name == "getKnowledgeSources":
            from app.knowledge.provenance import sources

            data = sources(c, p, revision_id)
        elif name == "getKnowledgeCandidate":
            data = service.detail(c, p, knowledge_id, candidate=True)
        elif name == "createKnowledge":
            data = service.create(c, p, idempotency_key, body)
        elif name == "getPublishedKnowledge":
            data = service.published(c, p, knowledge_id)
        elif name == "reviseKnowledge":
            data = service.revise(c, p, idempotency_key, knowledge_id, body)
        elif name == "getCandidateRevision":
            data = service.read_candidate(c, p, revision_id)
        elif name == "requestReview":
            data = reviews.request_review(c, p, idempotency_key, body)
        elif name == "getReview":
            data = reviews.read_review(c, p, request_id)
        elif name == "submitHumanDecision":
            data = reviews.human_decision(c, p, idempotency_key, request_id, body)
        elif name == "publishKnowledge":
            data = reviews.publish(c, p, idempotency_key, knowledge_id, body)
        elif name == "approveKnowledgePublication":
            data = reviews.approve_publish(c, p, idempotency_key, request_id, body)
        else:
            from app.knowledge.tasks import start_extract

            data = start_extract(c, p, idempotency_key, report_id, body)
        data = project(spec.response, data).model_dump(mode="json")
    if name == "extractKnowledge" or name == "requestReview" and body.execute_ai:
        from app.knowledge.worker import dispatch_knowledge

        tid = data["id"] if name == "extractKnowledge" else data["task"]["id"]
        dispatch_knowledge(p.org_id, tid)
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
