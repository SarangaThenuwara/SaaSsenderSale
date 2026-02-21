from .celery_app import celery_app
from .db import db
from .services.bounce_monitor import scan_user_bounces
from .services.recruiter_manager import process_recruiters_batch
# from .services.data_feed import fetch_new_recruiters # Hypothetical

import logging

LOG = logging.getLogger(__name__)

@celery_app.task
def task_scan_user_bounces(user_id):
    scan_user_bounces(user_id)

@celery_app.task
def trigger_bounce_scans():
    """
    Fan-out task to trigger bounce scanning for all active users.
    """
    # Find users who have sent emails recently? or all active?
    # All active is safer.
    users = db.users.find({"is_blocked": False, "is_deleted": False}, {"_id": 1})
    for u in users:
        task_scan_user_bounces.delay(str(u["_id"]))
    return {"triggered": True}

@celery_app.task
def task_process_new_recruiter_batch(recruiters_data):
    process_recruiters_batch(recruiters_data)

@celery_app.task
def weekly_recruiter_update_trigger():
    # Placeholder for the weekly update source
    # In a real app, this would fetch from an external API or file
    LOG.info("Weekly recruiter update triggered.")
    # data = fetch_new_recruiters()
    # for batch in chunks(data, 1000):
    #     task_process_new_recruiter_batch.delay(batch)
@celery_app.task
def purge_deleted_accounts():
    """
    Permanently purges accounts that have been soft-deleted for > 90 days.
    """
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=90)
    
    # 1. Find targets
    targets = list(db.users.find({"is_deleted": True, "deleted_at": {"$lt": cutoff}}, {"_id": 1}))
    target_ids = [t["_id"] for t in targets]
    
    if not target_ids:
        return {"purged_count": 0}
        
    # 2. Cascade delete (Ledger, recipients)
    # We keep it simple: Wipe the core records.
    res_users = db.users.delete_many({"_id": {"$in": target_ids}})
    res_ledger = db.user_recruiter_ledger.delete_many({"user_id": {"$in": target_ids}})
    
    LOG.info(f"PURGE: Permanently deleted {res_users.deleted_count} stale accounts and cleaned up ledgers.")
    return {"purged_count": res_users.deleted_count}
