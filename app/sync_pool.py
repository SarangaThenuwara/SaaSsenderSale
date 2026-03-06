import logging
import datetime
from .celery_app import celery_app
from .db import db, client
from .config import RECRUITER_SOURCE_DB, RECRUITER_SOURCE_COLLECTION

LOG = logging.getLogger(__name__)


def _do_sync(source_name=None):
    """
    Core sync logic — runs WITHOUT Celery, usable from BackgroundTasks or Celery.
    """
    if source_name is None:
        source_name = f"{RECRUITER_SOURCE_DB}.{RECRUITER_SOURCE_COLLECTION}"

    from app.services.recruiter_manager import process_recruiters_batch

    # Resolve source collection
    if "." in source_name:
        db_name, coll_name = source_name.split(".", 1)
        source_coll = client[db_name][coll_name]
    else:
        source_coll = db[source_name]

    LOG.info(f"Syncing from: {source_coll.database.name}.{source_coll.name}")

    source_cursor = source_coll.find({})
    batch = []
    total_synced = 0

    for doc in source_cursor:
        email = doc.get("email")
        if not email:
            continue
        batch.append({
            "email": email.strip().lower(),
            "name": (doc.get("name") or doc.get("full_name") or "").strip(),
            "company": (doc.get("company") or doc.get("company_name") or "").strip(),
            "source": f"sync:{source_name}"
        })

        if len(batch) >= 1000:
            process_recruiters_batch(batch)
            total_synced += len(batch)
            batch = []

    if batch:
        process_recruiters_batch(batch)
        total_synced += len(batch)

    LOG.info(f"Sync complete: {total_synced} recruiters from {source_name}")
    return {"count": total_synced, "status": "success"}


@celery_app.task
def sync_from_main_database(source_name=None):
    """Celery-wrapped version of _do_sync for scheduled/background jobs."""
    try:
        return _do_sync(source_name)
    except Exception as e:
        LOG.exception(f"Celery sync failed: {e}")
        return {"status": "error", "message": str(e)}
