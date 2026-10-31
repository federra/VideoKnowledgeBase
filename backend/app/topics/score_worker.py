"""Dedicated bounded scoring delivery; broker only receives opaque identifiers."""

from uuid import UUID

from app.tasks.celery_app import app


@app.task(name="cip.score_topic", ignore_result=True, soft_time_limit=660, time_limit=690)
def execute(org_id, task_id):
    from app.core.database import application_engine
    from app.tasks.service import Runner
    from app.topics.scoring import KIND, LegacyScore, Score

    try:
        org, tid = UUID(org_id), UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        return
    engine = application_engine()
    try:
        Runner(engine, {(KIND, "1"): LegacyScore(), (KIND, "2"): Score()}, lease_seconds=720).run(
            org, tid
        )
    finally:
        engine.dispose()


def dispatch_score(org, tid):
    try:
        execute.apply_async(args=[str(org), str(tid)], queue="topics", retry=False)
    except Exception:  # noqa: BLE001 - durable queued task is preserved
        return False
    return True
