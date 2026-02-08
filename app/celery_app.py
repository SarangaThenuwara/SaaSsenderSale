from celery import Celery
from .config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery(
    "app",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

# You can load periodic tasks etc. from here if needed
celery_app.conf.task_routes = {
    "app.send_worker.send_batch_for_user": {"queue": "send_queue"},
    "app.assigner.assign_pending_recipients": {"queue": "assign_queue"},
}

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "reset-daily-limits-midnight": {
        "task": "app.send_worker.reset_daily_limits",
        "schedule": crontab(hour=0, minute=0),
    },
    "auto-assign-recipients": {
        "task": "app.assigner.assign_pending_recipients",
        "schedule": crontab(minute="*/30"), # Every 30 mins
    }
}