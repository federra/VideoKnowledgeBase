"""Feedback deliveries keep long model calls off the default short-lived queue."""
from unittest.mock import Mock


def test_feedback_delivery_uses_private_bounded_queue(monkeypatch):
    from app.ai import feedback_worker
    delivery = Mock()
    monkeypatch.setattr(feedback_worker.execute, 'apply_async', delivery)
    assert feedback_worker.dispatch_feedback('org', 'task')
    delivery.assert_called_once_with(args=['org', 'task'], queue='feedback', retry=False)
    assert feedback_worker.execute.soft_time_limit == 660
    assert feedback_worker.execute.time_limit == 690
    delivery.side_effect = RuntimeError('broker unavailable')
    assert not feedback_worker.dispatch_feedback('org', 'task')


def test_feedback_handler_and_queue_are_registered():
    from app.tasks.celery_app import app
    from app.tasks.handlers import registry
    assert ('audience.feedback', '2') in registry()
    assert 'feedback' in {q.name for q in app.conf.task_queues}
