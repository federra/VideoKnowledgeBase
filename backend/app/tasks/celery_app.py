"""Private JSON transport. PostgreSQL, not the Celery backend, owns task facts."""

from celery import Celery, current_app, signals
from kombu import Exchange, Queue

from app.core.config import settings

app = Celery(
    "cip",
    broker=settings.redis_url.get_secret_value(),
    include=["app.tasks.worker", "app.research.worker", "app.knowledge.worker"],
)
app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=2,
    task_soft_time_limit=50,
    task_time_limit=60,
    task_publish_retry=False,
    broker_connection_timeout=3,
    broker_transport_options={
        "visibility_timeout": 120,
        "socket_timeout": 3,
        "socket_connect_timeout": 3,
        "retry_on_timeout": False,
        "global_keyprefix": settings.task_key_prefix,
    },
    task_default_queue=settings.task_queue,
    task_create_missing_queues=False,
    task_queues=(
        Queue(
            "knowledge.analysis",
            exchange=Exchange("knowledge.analysis", type="direct"),
            routing_key="knowledge.analysis",
        ),
        Queue(settings.task_queue),
        Queue("research", exchange=Exchange("research", type="direct"), routing_key="research"),
        Queue(
            "research.analysis",
            exchange=Exchange("research.analysis", type="direct"),
            routing_key="research.analysis",
        ),
    ),
    timezone="UTC",
    enable_utc=True,
    beat_schedule={"persistent-task-dispatch": {"task": "cip.tick", "schedule": 10.0}},
    worker_hijack_root_logger=False,
    worker_send_task_events=False,
    task_send_sent_event=False,
)


@signals.worker_process_init.connect
def initialize_child_trace(**kwargs):
    """macOS spawn starts with empty module globals; initialize inside the child.

    Celery 5.6's prefork initializer only populates trace._localized in its execv
    branch, but macOS spawn also needs it. Keep this compatibility hook beside
    the pinned 5.6 dependency; never patch installed packages or pretend to fork.
    """
    from celery.app.trace import setup_worker_optimizations

    setup_worker_optimizations(current_app._get_current_object())
