import logging
import datetime
from .celery_app import celery_app
from .db import db, client

LOG = logging.getLogger(__name__)

@celery_app.task
def sync_from_main_database(source_name="HR.UAE"):

    """
    Syncs new recruiter records from a source collection into the 'recipients' pool.
    Uses email as a deduplication key.
    """
    try:
        # Resolve source collection
        # Default to HR.UAE in the primary database
        source_coll = db[source_name]
        
        # If it's a dot-separated name, it might be db_name.coll_name
        if "." in source_name:
            try:
                # Check if it's explicitly a separate database
                parts = source_name.split(".")
                test_db = client[parts[0]]
                if parts[1] in test_db.list_collection_names():
                    source_coll = test_db[parts[1]]
            except:
                pass

        LOG.info(f"Syncing from source collection: {source_coll.database.name}.{source_coll.name}")
        
        from pymongo import UpdateOne
        operations = []
        source_cursor = source_coll.find({})
        
        now = datetime.datetime.utcnow()
        new_count = 0
        for doc in source_cursor:
            email = doc.get("email")
            if not email:
                continue
            
            email = email.strip().lower()
            
            # Use UpdateOne with upsert=True on email 
            # This ensures even if something was deleted or modified manually, we preserve unique emails.
            # $setOnInsert ensures we only set status=Pending for NEW records.
            operations.append(UpdateOne(
                {"email": email},
                {
                    "$setOnInsert": {
                        "email": email,
                        "name": (doc.get("name") or doc.get("full_name") or "").strip(),
                        "company": (doc.get("company") or doc.get("company_name") or "").strip(),
                        "status": "Pending",
                        "source": source_name,
                        "created_at": now
                    }
                },
                upsert=True
            ))

            if len(operations) >= 1000:
                res = db.recipients.bulk_write(operations, ordered=False)
                new_count += res.upserted_count
                operations = []

        if operations:
            res = db.recipients.bulk_write(operations, ordered=False)
            new_count += res.upserted_count

        LOG.info(f"Successfully synced {new_count} new recruiters.")
        return {"count": new_count, "status": "success"}


    except Exception as e:
        LOG.exception(f"Sync failed for {source_name}")
        return {"status": "error", "message": str(e)}
