from celery import Celery
from .config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery(
    "app",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.tasks", "app.sync_pool"]
)

# You can load periodic tasks etc. from here if needed
celery_app.conf.task_routes = {
    "app.send_worker.send_batch_for_user": {"queue": "send_queue"},
    "app.assigner.assign_pending_recipients": {"queue": "assign_queue"},
    "app.sync_pool.sync_from_main_database": {"queue": "sync_queue"},
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
    },
    "auto-sync-pool": {
        "task": "app.sync_pool.sync_from_main_database",
        "schedule": crontab(minute=0), # Every hour at the top of the hour
    },
    "purge-old-deleted-users": {
        "task": "app.send_worker.purge_deleted_users",
        "schedule": crontab(hour=3, minute=0), # Daily at 3 AM
    },
    "trigger_bounce_scans_hourly": {
        "task": "app.tasks.trigger_bounce_scans",
        "schedule": crontab(minute=15), # Hourly at 15 mins past
    },
    "weekly_recruiter_update": {
        "task": "app.tasks.weekly_recruiter_update_trigger",
        "schedule": crontab(day_of_week=1, hour=2, minute=0), # Monday at 2 AM
    }
}