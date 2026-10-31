"""S05.4 policy tests; business facts are verified separately on PostgreSQL."""

import pytest


def test_retry_is_bounded_and_only_allowlisted_local_failures():
    from app.tasks.policy import retry_delay

    assert retry_delay("LOCAL_TRANSIENT", 1, 3) == 2
    assert retry_delay("LEASE_LOST", 2, 3) == 4
    for code in ["EXTERNAL_RESULT_UNKNOWN", "INVALID_INPUT", "ACCESS_REVOKED", "INTERNAL_ERROR"]:
        assert retry_delay(code, 1, 3) is None
    assert retry_delay("LOCAL_TRANSIENT", 3, 3) is None
    with pytest.raises(ValueError):
        retry_delay("LOCAL_TRANSIENT", 0, 3)


def test_celery_transport_has_no_business_results_or_unbounded_retries():
    from app.tasks.celery_app import app

    assert app.conf.accept_content == ["json"]
    assert app.conf.task_acks_late
    assert app.conf.task_reject_on_worker_lost
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_ignore_result
    assert app.conf.task_soft_time_limit < app.conf.task_time_limit < 90
    assert app.conf.beat_schedule["persistent-task-dispatch"]["task"] == "cip.tick"
    assert app.conf.task_publish_retry is False


@pytest.mark.parametrize('kind',['collect.hongguo.saved','collect.creator-posts.resume','collect.microfilm.resume'])
def test_explicit_recovery_task_is_never_claimed_by_generic_worker(monkeypatch,kind):
    from app.tasks import worker
    from uuid import uuid4

    class Connection:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def exec_driver_sql(self,*args): return self
        def scalar_one_or_none(self): return kind
    class Engine:
        def connect(self): return Connection()
    class Runtime:
        engine=Engine()
        def run(self,*args): raise AssertionError('generic worker must leave explicit recovery queued')
    monkeypatch.setattr(worker,'runtime',lambda:Runtime())
    worker.execute(str(uuid4()),str(uuid4()))
