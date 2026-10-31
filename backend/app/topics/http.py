from fastapi.responses import JSONResponse

from app.contracts.api import Operation, add_operation
from app.contracts.models import Envelope
from app.security.http import preflight
from app.security.sessions import authenticate
from app.topics import contracts as t
from app.topics import generation, service

OPERATIONS = [
    Operation(
        "GET",
        "/topics",
        "listTopics",
        t.TopicList,
        ("content.read",),
        "S08.2",
        query=t.TopicQuery,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/topics",
        "createTopic",
        t.TopicView,
        ("content.write",),
        "S08.2",
        request=t.TopicWrite,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/topics/generate",
        "generateTopics",
        t.GenerationView,
        ("content.write",),
        "S08.2",
        request=t.GenerateRequest,
        status=202,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/topics/generations/{generation_id}",
        "getTopicGeneration",
        t.GenerationView,
        ("content.read",),
        "S08.2",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/topics/generations/{generation_id}/save",
        "saveGeneratedTopic",
        t.TopicView,
        ("content.write",),
        "S08.2",
        request=t.GenerationSave,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/topics/{topic_id}",
        "getTopic",
        t.TopicView,
        ("content.read",),
        "S08.2",
        implementation="implemented",
    ),
    Operation(
        "PATCH",
        "/topics/{topic_id}",
        "reviseTopic",
        t.TopicView,
        ("content.write",),
        "S08.2",
        request=t.TopicUpdate,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/topics/{topic_id}/select",
        "selectTopic",
        t.TopicView,
        ("content.write",),
        "S08.2",
        request=t.TopicSelect,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/topics/{topic_id}/handoff",
        "handoffTopic",
        t.HandoffView,
        ("content.export",),
        "S08.2",
        request=t.TopicHandoff,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/sparks",
        "listSparks",
        t.SparkList,
        ("content.read",),
        "S08.2",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/sparks",
        "saveSpark",
        t.SparkView,
        ("content.write",),
        "S08.2",
        request=t.SparkWrite,
        implementation="implemented",
    ),
]


def dispatch(
    *,
    request,
    engine,
    session=None,
    body=None,
    filters=None,
    topic_id=None,
    generation_id=None,
    idempotency_key=None,
    csrf_token=None,
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    name = spec.name
    key = str(idempotency_key)
    with engine.begin() as c:
        p = authenticate(c, session)
        if name == "listTopics":
            data = service.listing(
                c, p, filters.business_code, filters.pool, filters.page, filters.q, filters.status
            )
        elif name == "createTopic":
            data = service.create(c, p, key, body)
        elif name == "getTopic":
            data = service.topic(c, p, topic_id)
        elif name == "reviseTopic":
            data = service.revise(c, p, key, topic_id, body)
        elif name == "selectTopic":
            data = service.choose(c, p, key, topic_id, body)
        elif name == "handoffTopic":
            data = service.handoff(c, p, key, topic_id, body)
        elif name == "listSparks":
            data = service.sparks(c, p)
        elif name == "saveSpark":
            data = service.save_spark(c, p, key, body)
        elif name == "generateTopics":
            data = generation.start(c, p, key, body)
        elif name == "getTopicGeneration":
            data = generation.read(c, p, generation_id)
        else:
            data = generation.save(c, p, key, generation_id, body)
    if name == "generateTopics" and data["state"] == "queued":
        from app.topics.worker import dispatch_generation

        dispatch_generation(p.org_id, data["id"])
    payload = Envelope[spec.response](request_id=request.state.request_id, data=data)
    return JSONResponse(
        payload.model_dump(mode="json"),
        status_code=spec.status,
        headers={"Cache-Control": "no-store", "X-Request-ID": str(request.state.request_id)},
    )


def mount(app):
    for spec in OPERATIONS:
        add_operation(spec, app, dispatch, preflight)
