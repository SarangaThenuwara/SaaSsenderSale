import logging
import datetime
from .celery_app import celery_app
from .db import db, client

LOG = logging.getLogger(__name__)

@celery_app.task
def sync_from_main_database(source_name="hremail.email"):
    """
    Syncs new recruiter records from a source collection into the master pool.
    Uses the modern recruiter_manager for propagation.
    """
    try:
        from app.services.recruiter_manager import process_recruiters_batch
        
        # Resolve source collection
        source_coll = None
        if "." in source_name:
            # db_name.coll_name
            db_name, coll_name = source_name.split(".")
            source_coll = client[db_name][coll_name]
        else:
            source_coll = db[source_name]

        LOG.info(f"Syncing from source collection: {source_coll.database.name}.{source_coll.name}")
        
        source_cursor = source_coll.find({})
        batch = []
        total_synced = 0
        
        for doc in source_cursor:
            email = doc.get("email")
            if not email:
                continue
            
            # Prepare data in format expected by process_recruiters_batch
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

        LOG.info(f"Successfully processed {total_synced} recruiters from {source_name}")
        return {"count": total_synced, "status": "success"}

    except Exception as e:
        LOG.exception(f"Sync failed for {source_name}")
        return {"status": "error", "message": str(e)}
