import datetime
from .db import db
from pymongo import ReturnDocument

RECIPIENTS = db.recipients
USERS = db.users

def assign_pending_recipients(max_assign=5000):
    """
    Capacity-aware round-robin assignment of pending recipients to active users.
    """
    now = datetime.datetime.utcnow()
    # build active users with capacity
    users = list(USERS.find({"active": True, "needs_reauth": {"$ne": True}}))
    # compute capacity
    for u in users:
        u["daily_sent"] = u.get("daily_sent", 0)
        u["capacity"] = max(0, u.get("daily_limit", 300) - u["daily_sent"])

    # filter users with capacity > 0
    users = [u for u in users if u["capacity"] > 0]
    if not users:
        return {"assigned": 0, "reason": "no_capacity"}

    # iterate pending recipients and assign
    assigned = 0
    user_idx = 0
    pending_cursor = RECIPIENTS.find({"status": "Pending"}).sort("created_at", 1).limit(max_assign)
    for r in pending_cursor:
        # find next user with capacity
        found = None
        for _ in range(len(users)):
            u = users[user_idx]
            user_idx = (user_idx + 1) % len(users)
            if u["capacity"] > 0:
                found = u
                break
        if not found:
            break

        res = RECIPIENTS.find_one_and_update(
            {"_id": r["_id"], "status": "Pending"},
            {"$set": {"status": "Assigned", "assigned_to": found["_id"], "assigned_at": now, "assigned_by": "system"}},
            return_document=ReturnDocument.AFTER
        )
        if res:
            found["capacity"] -= 1
            assigned += 1

    return {"assigned": assigned}