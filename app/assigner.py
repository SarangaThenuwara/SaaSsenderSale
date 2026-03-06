import datetime
import logging
from .db import db

LOG = logging.getLogger(__name__)

def assign_pending_recipients(max_assign=1000):
    """
    Populates the user_recruiter_ledger for active users.
    Randomly assigns recruiters from the global pool that haven't been assigned yet,
    replenishing their 'pending' queue efficiently.
    """
    now = datetime.datetime.utcnow()
    
    # Active users who aren't blocked or deleted
    users = list(db.users.find({
        # Populate their queue regardless of them having connected Gmail yet
        # so they can see TARGET RECIPIENTS mapped out when they land on the dashboard.
        "is_blocked": {"$ne": True},
        "is_deleted": {"$ne": True}
    }))
    
    assigned_total = 0
    
    for u in users:
        active_campaign_id = u.get("active_campaign_id", "default")
        uid = u["_id"]
        
        # Check current pending queue size
        pending_count = db.user_recruiter_ledger.count_documents({
            "userId": uid, 
            "status": "pending",
            "campaignId": active_campaign_id
        })
        
        # If they already have a healthy buffer, skip to save resources
        if pending_count > 500:
            continue
            
        # Get all recruiter IDs this user has EVER interacted with 
        # (pending, sent, failed, etc) to ensure we don't message the same person twice
        assigned_ids = db.user_recruiter_ledger.find({"userId": uid}).distinct("recruiterId")
        
        # Sample completely new recruiters for them
        pipeline = [
            {"$match": {"_id": {"$nin": assigned_ids}, "health": "good"}},
            {"$sample": {"size": max_assign}}
        ]
        
        new_recruiters = list(db.recruiters.aggregate(pipeline))
        
        if not new_recruiters:
            continue
            
        ledger_ops = []
        for r in new_recruiters:
            ledger_ops.append({
                "userId": uid,
                "recruiterId": r["_id"],
                "campaignId": active_campaign_id,
                "status": "pending",
                "country": r.get("detectedCountry"),
                "provider": r.get("providerType"),
                "lastAttempt": None,
                "created_at": now
            })
            
        if ledger_ops:
            try:
                db.user_recruiter_ledger.insert_many(ledger_ops, ordered=False)
                assigned_total += len(ledger_ops)
            except Exception as e:
                LOG.error(f"Error inserting ledger ops for user {uid}: {e}")
            
    return {"assigned": assigned_total}