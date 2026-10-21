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
            "SELECT kind FROM tasks WHERE org_id=%s AND id=%s", (org, tid)
        ).scalar_one_or_none()
    # One-shot public novel batches run only in the explicit local CLI Runner.
    # Ignore even a stale/manual common-queue delivery, without changing task state.
    if kind in ("collect.novels", "collect.hongguo"):
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
