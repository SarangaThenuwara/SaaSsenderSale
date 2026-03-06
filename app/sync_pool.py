import logging
import datetime
from .celery_app import celery_app
from .db import db, client
from .config import RECRUITER_SOURCE_DB, RECRUITER_SOURCE_COLLECTION

LOG = logging.getLogger(__name__)

SYNC_STATE_KEY = "recruiter_sync_state"


def _get_last_sync_time():
    """Get the last time we successfully synced, stored in db.settings."""
    state = db.settings.find_one({"_id": SYNC_STATE_KEY})
    return state.get("last_sync_at") if state else None


def _save_last_sync_time(ts):
    db.settings.update_one(
        {"_id": SYNC_STATE_KEY},
        {"$set": {"last_sync_at": ts, "updated_at": datetime.datetime.utcnow()}},
        upsert=True
    )


def _do_sync(source_name=None, limit=500):
    """
    Incremental sync — only fetches records newer than the last sync timestamp.
    `limit` caps the number of docs per call to stay within Vercel's 60s timeout.
    Celery scheduled runs use a higher default limit.
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

    last_sync = _get_last_sync_time()
    sync_started_at = datetime.datetime.utcnow()

    # Build query: only fetch newer docs if we have a prior sync time
    query = {}
    if last_sync:
        query["timestamp"] = {"$gt": last_sync}

    LOG.info(f"Incremental sync from {source_coll.database.name}.{source_coll.name} "
             f"since {last_sync or 'beginning'}, limit={limit}")

    source_cursor = source_coll.find(query).sort("timestamp", 1).limit(limit)
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

        if len(batch) >= 200:
            process_recruiters_batch(batch)
            total_synced += len(batch)
            batch = []

    if batch:
        process_recruiters_batch(batch)
        total_synced += len(batch)

    # Save new sync timestamp so next run continues from here
    if total_synced > 0 or last_sync is None:
        _save_last_sync_time(sync_started_at)

    LOG.info(f"Sync complete: {total_synced} new recruiters from {source_name}")
    return {
        "count": total_synced,
        "status": "success",
        "incremental": last_sync is not None,
        "since": last_sync.isoformat() if last_sync else "beginning"
    }


@celery_app.task
def sync_from_main_database(source_name=None):
    """Celery-wrapped version of _do_sync — processes up to 5000 docs per scheduled run."""
    try:
        return _do_sync(source_name, limit=5000)
    except Exception as e:
        LOG.exception(f"Celery sync failed: {e}")
        return {"status": "error", "message": str(e)}
