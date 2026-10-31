"""Bounded feedback analysis; broker receives only opaque identifiers."""

from uuid import UUID

from app.tasks.celery_app import app


@app.task(name="cip.analyze_feedback", ignore_result=True, soft_time_limit=660, time_limit=690)
def execute(org_id, task_id):
    from app.core.database import application_engine
    from app.intelligence.feedback_v2 import KIND, VERSION, FeedbackV2
    from app.intelligence.feedback_v3 import FeedbackV3
    from app.tasks.service import Runner

    try:
        org, tid = UUID(org_id), UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        return
    engine = application_engine()
    try:
        Runner(engine, {(KIND, VERSION): FeedbackV2(),(KIND,"3"):FeedbackV3()}, lease_seconds=720).run(org, tid)
    finally:
        engine.dispose()


def dispatch_feedback(org, tid):
    try:
        execute.apply_async(args=[str(org), str(tid)], queue="feedback", retry=False)
    except Exception:  # noqa: BLE001 - durable queued task survives broker outage
        return False
    return True
