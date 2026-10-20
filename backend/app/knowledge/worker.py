"""Explicit AI-only queue, disabled until an operator starts its worker."""

from uuid import UUID

from app.tasks.celery_app import app


@app.task(name="cip.knowledge_analysis", ignore_result=True)
def execute(org_id, task_id):
    from app.core.database import application_engine
    from app.knowledge.tasks import KnowledgeTask
    from app.tasks.service import Runner

    try:
        org, tid = UUID(org_id), UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        return
    engine = application_engine()
    try:
        Runner(
            engine, {("knowledge." + p, "2"): KnowledgeTask(p) for p in ("extract", "review")}
        ).run(org, tid)
    finally:
        engine.dispose()


def dispatch_knowledge(org, tid):
    try:
        execute.apply_async(args=[str(org), str(tid)], queue="knowledge.analysis", retry=False)
    except Exception:  # noqa: BLE001 - durable queued row survives broker failure
        return False
