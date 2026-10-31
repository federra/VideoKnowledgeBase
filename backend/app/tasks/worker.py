"""Celery adapters: no user content, tokens, URLs or secrets in broker messages/logs."""

from functools import lru_cache
from uuid import UUID

from app.core.database import application_engine
from app.tasks.celery_app import app
from app.tasks.handlers import registry
from app.tasks.service import Runner, sweep


@lru_cache(maxsize=1)
def runtime():
    # Construct after prefork; never share a parent SQL connection across child processes.
    return Runner(application_engine(), registry())


def knowledge_queue(org, tid):
    with runtime().engine.connect() as c:
        kind = c.exec_driver_sql(
            "SELECT CASE WHEN idempotency_key LIKE 'refresh/%%' THEN 'intelligence.refresh' ELSE kind END FROM tasks WHERE org_id=%s AND id=%s",
            (org, tid),
        ).scalar_one_or_none()
    # One-shot public novel batches run only in the explicit local CLI Runner.
    # Ignore even a stale/manual common-queue delivery, without changing task state.
    if kind in (
        "knowledge.genre_explain",
        "collect.novels",
        "collect.hongguo",
        "collect.hongguo.saved",
        "collect.creator-posts.resume",
        "collect.microfilm.resume",
        "collect.tikhub-series",
        "series.normalize",
        "intelligence.refresh",
        "intelligence.refresh.resume",
        "creator.resolve",
        "collect.creator-series",
        "collect.creator-posts",
        "collect.microfilm",
        "creator.series.reparse",
        "creator.browser.comments",
        "creator.browser.reparse",
    ):
        return True
    if kind == "topic.score":
        from app.topics.score_worker import dispatch_score
        dispatch_score(org, tid)
        return True
    if kind == "audience.feedback":
        from app.ai.feedback_worker import dispatch_feedback

        dispatch_feedback(org, tid)
        return True
    if kind == "topic.generate":
        from app.topics.worker import dispatch_generation
        dispatch_generation(org, tid)
        return True
    if kind in ("knowledge.extract", "knowledge.review"):
        from app.knowledge.worker import dispatch_knowledge

        dispatch_knowledge(org, tid)
        return True
    return False


@app.task(name="cip.execute", ignore_result=True)
def execute(org_id, task_id):
    try:
        org, tid = UUID(org_id), UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        return
    if not knowledge_queue(org, tid):
        runtime().run(org, tid)


def dispatch(org, tid):
    if knowledge_queue(org, tid):
        return
    execute.apply_async(args=[str(org), str(tid)], retry=False)


@app.task(name="cip.tick", ignore_result=True)
def tick():
    from app.collection.schedule import schedule

    schedule(runtime())
    sweep(runtime(), dispatch)


@app.task(name="cip.knowledge_retention", ignore_result=True)
def knowledge_retention():
    from app.knowledge.retention import maintain

    maintain(runtime().engine)
