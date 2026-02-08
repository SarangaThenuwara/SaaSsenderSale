import logging
import datetime
from .db import db, client

LOG = logging.getLogger(__name__)

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
        
        # Get all existing emails to avoid duplicates
        existing_emails = set(db.recipients.distinct("email"))
        
        new_records = []
        source_cursor = source_coll.find({})
        
        now = datetime.datetime.utcnow()
        for doc in source_cursor:
            email = doc.get("email")
            if not email:
                continue
            
            # Basic validation/cleanup
            email = email.strip().lower()
            if not email or email in existing_emails:
                continue
            
            new_records.append({
                "email": email,
                "name": (doc.get("name") or doc.get("full_name") or "").strip(),
                "company": (doc.get("company") or doc.get("company_name") or "").strip(),
                "status": "Pending",
                "source": source_name,
                "created_at": now
            })
            existing_emails.add(email)

        if new_records:
            db.recipients.insert_many(new_records)
            LOG.info(f"Successfully synced {len(new_records)} new recruiters.")
            return {"count": len(new_records), "status": "success"}
        
        return {"count": 0, "status": "no_new_records"}

    except Exception as e:
        LOG.exception(f"Sync failed for {source_name}")
        return {"status": "error", "message": str(e)}
