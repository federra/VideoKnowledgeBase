"""Topic worker: opaque IDs only; no automatic paid retry."""

from uuid import UUID

from app.tasks.celery_app import app


@app.task(name="cip.generate_topics", ignore_result=True, soft_time_limit=1260, time_limit=1290)
def execute(org_id, task_id):
    from app.core.database import application_engine
    from app.tasks.service import Runner
    from app.topics.generation import KIND, VERSION, Generate
    from app.topics.generation_v2 import VERSION as V2
    from app.topics.generation_v2 import GenerateV2

    try:
        org, tid = UUID(org_id), UUID(task_id)
    except (ValueError, TypeError, AttributeError):
        return
    engine = application_engine()
    try:
        Runner(
            engine, {(KIND, VERSION): Generate(), (KIND, V2): GenerateV2()}, lease_seconds=1320
        ).run(org, tid)
    finally:
        engine.dispose()


def dispatch_generation(org, tid):
    try:
        execute.apply_async(args=[str(org), str(tid)], queue="topics", retry=False)
    except Exception:  # noqa: BLE001 - durable task remains queued during broker outage
        return False
    return True
