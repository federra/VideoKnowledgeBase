"""Separate parsing and authorized analysis adapters; broker messages contain IDs only."""

from uuid import UUID

from app.tasks.celery_app import app


@app.task(name="cip.parse_research", ignore_result=True)
def execute_parse(org_id, task_id):
    from app.core.database import application_engine
    from app.processing.research import Parse
    from app.tasks.service import Runner

    try:
        org, tid = UUID(org_id), UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        return
    engine = application_engine()
    try:
        Runner(engine, {("research.parse", "1"): Parse()}).run(org, tid)
    finally:
        engine.dispose()


def dispatch_parse(org, tid):
    try:
        execute_parse.apply_async(args=[str(org), str(tid)], queue="research", retry=False)
    except Exception:  # noqa: BLE001 - durable task remains queued, no false parser result
        return False


@app.task(name="cip.analyze_research", ignore_result=True)
def execute_analysis(org_id, task_id):
    from app.core.database import application_engine
    from app.research.analysis_task import Analyze
    from app.tasks.service import Runner

    try:
        org, tid = UUID(org_id), UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        return
    engine = application_engine()
    try:
        Runner(
            engine,
            {("research." + p, "2"): Analyze(p) for p in ("decompose", "evaluate", "predict")},
        ).run(org, tid)
    finally:
        engine.dispose()


def dispatch_analysis(org, tid):
    try:
        execute_analysis.apply_async(
            args=[str(org), str(tid)], queue="research.analysis", retry=False
        )
    except Exception:  # noqa: BLE001 - durable row survives broker outage
        return False
