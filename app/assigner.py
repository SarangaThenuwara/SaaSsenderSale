import datetime
import random
from .db import db
from pymongo import ReturnDocument

RECIPIENTS = db.recipients
USERS = db.users

def assign_pending_recipients(max_assign=5000):
    """
    Capacity-aware randomized assignment of pending recipients to active users.
    Ensures that users get a different, random set of recruiters to avoid 
    footprinting and ensure fair distribution.
    """
    now = datetime.datetime.utcnow()
    
    # build active users who have campaign toggled on and credentials validated
    users = list(USERS.find({
        "campaign_active": True, 
        "is_blocked": {"$ne": True},
        "is_deleted": {"$ne": True},
        "credentials_valid": True,
        "needs_reauth": {"$ne": True}
    }))
    
    # Shuffle user list for intra-batch randomization
    random.shuffle(users)
    
    # compute current capacity for today
    for u in users:
        u["daily_sent"] = u.get("daily_sent", 0)
        u["capacity"] = max(0, u.get("daily_limit", 240) - u["daily_sent"])

    # filter users who actually have room to send more
    users = [u for u in users if u["capacity"] > 0]
    if not users:
        return {"assigned": 0, "reason": "no_capacity_or_no_active_users"}

    # Fetch a set of pending recipients. 
    # Use $sample or just fetch and shuffle. For performance with large pools, 
    # fetching a slice and shuffling is often better than a large $sample.
    pending_cursor = list(RECIPIENTS.find({"status": "Pending"}).limit(max_assign))
    random.shuffle(pending_cursor)
    
    assigned = 0
    user_idx = 0
    
    for r in pending_cursor:
        # find next user with capacity
        found = None
        # Loop through users starting from user_idx to find one with capacity
        for _ in range(len(users)):
            u = users[user_idx]
            user_idx = (user_idx + 1) % len(users)
            if u["capacity"] > 0:
                found = u
                break
        
        if not found:
            break

        # Transaction-safe assignment
        res = RECIPIENTS.find_one_and_update(
            {"_id": r["_id"], "status": "Pending"},
            {"$set": {
                "status": "Assigned", 
                "assigned_to": found["_id"], 
                "assigned_at": now, 
                "assigned_by": "random_assigner_v2"
            }},
            return_document=ReturnDocument.AFTER
        )
        
        if res:
            found["capacity"] -= 1
            assigned += 1

    return {"assigned": assigned}