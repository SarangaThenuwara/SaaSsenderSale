import logging
from datetime import datetime
from pymongo import UpdateOne, InsertOne
from app.db import db
from app.services.country_detection import detect_country, classify_email_provider

LOG = logging.getLogger(__name__)

BATCH_SIZE = 1000

def process_recruiters_batch(recruiters_data: list):
    """
    recruiters_data: List of dicts, e.g., [{"email": "foo@bar.com", "name": "..."}]
    """
    
    operations = []
    new_recruiters = []
    
    # 1. Prepare bulk upserts for global list
    for r in recruiters_data:
        email = r.get("email").lower().strip()
        domain = email.split("@")[-1]
        
        # Check if already exists to avoid re-processing country (optimization)
        existing = db.recruiters.find_one({"email": email}, {"_id": 1})
        if existing:
             # Just update metadata if needed, skip heavy logic
             operations.append(
                UpdateOne(
                    {"email": email},
                    {"$set": {"last_seen": datetime.utcnow()}, "$setOnInsert": {"created_at": datetime.utcnow()}},
                    upsert=True
                )
             )
             new_recruiters.append(None) # Keep parallel with operations
             continue

        # New recruiter logic
        provider_type = classify_email_provider(domain)
        country_info = detect_country(domain) if provider_type != "free" else {"country": "Global", "confidence": 1.0}
        
        doc = {
            "email": email,
            "name": r.get("name"),
            "domain": domain,
            "providerType": provider_type,
            "detectedCountry": country_info.get("country", "Unknown"),
            "confidence": country_info.get("confidence", 0.0),
            "health": "good",
            "bounceCount": 0,
            "enrichmentMetadata": r.get("metadata", {}),
            "source": r.get("source", "upload"),
            "created_at": datetime.utcnow(),
            "last_seen": datetime.utcnow()
        }
        
        # Better: Use `bulk_write` with `UpdateOne(upsert=True)`.
        operations.append(
            UpdateOne(
                {"email": email},
                {"$setOnInsert": doc},
                upsert=True
            )
        )
        new_recruiters.append(doc)

    if operations:
        try:
            result = db.recruiters.bulk_write(operations, ordered=False)
            LOG.info(f"Upserted {len(operations)} recruiters. Upserts: {result.upserted_count}, Matches: {result.matched_count}")
            
            # 2. Propagate NEW recruiters to Users
            
            new_recruiters_info = []
            # result.upserted_ids is a dict {index: _id}
            for idx, _id in result.upserted_ids.items():
                # We need the metadata (country, provider) for optimized ledger
                # 'new_recruiters' list matches the order of 'operations'
                recruiter_doc = new_recruiters[idx] 
                if recruiter_doc:
                    new_recruiters_info.append({
                        "_id": _id,
                        "country": recruiter_doc.get("detectedCountry"),
                        "provider": recruiter_doc.get("providerType")
                    })
                
            if new_recruiters_info:
                propagate_to_users(new_recruiters_info)
                
        except Exception as e:
            LOG.exception("Error processing recruiters batch")
            raise e

def propagate_to_users(recruiters_info):
    """
    recruiters_info: List of dicts with {_id, country, provider}
    """
    # This might be heavy if users * recruiters is large.
    # Process in chunks of users.
    
    users = list(db.users.find({"is_deleted": False, "is_blocked": False}, {"_id": 1}))
    
    ledger_ops = []
    
    for uid in users:
        for r_info in recruiters_info:
            ledger_ops.append(
                InsertOne({
                    "userId": uid["_id"],
                    "recruiterId": r_info["_id"],
                    "campaignId": "default", # Or specific logical grouping
                    "status": "pending",
                    # denormalized fields for filtering
                    "country": r_info.get("country"),
                    "provider": r_info.get("provider"),
                    "lastAttempt": None,
                    "created_at": datetime.utcnow()
                })
            )
            
        if len(ledger_ops) >= BATCH_SIZE:
             try:
                 db.user_recruiter_ledger.bulk_write(ledger_ops, ordered=False)
             except Exception as e:
                 LOG.warning(f"Bulk write error (likely duplicates) in ledger propagation: {e}")
             ledger_ops = []
    
    if ledger_ops:
        try:
            db.user_recruiter_ledger.bulk_write(ledger_ops, ordered=False)
        except Exception as e:
            LOG.warning(f"Bulk write error (likely duplicates) in ledger propagation: {e}")

