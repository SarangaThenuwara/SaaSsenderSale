import logging
import base64
import re
from datetime import datetime
from app.db import db
from app.gmail_helpers import get_gmail_service_for_user
from googleapiclient.errors import HttpError

LOG = logging.getLogger(__name__)

# Constants
BOUNCE_THRESHOLD = 0.05  # 5% bounce rate pauses campaign
HARD_BOUNCE_KEYWORDS = [
    "550", "5.1.1", "does not exist", "address not found", "rejected", "disabled", "quota exceeded"
]

def scan_user_bounces(user_id):
    """
    Scans the user's Gmail for bounce messages (mailer-daemon), parses them,
    updates recruiter health, suppression list, and user's stats.
    """
    try:
        service = get_gmail_service_for_user(user_id)
    except Exception as e:
        LOG.warning(f"Could not get Gmail service for user {user_id}: {e}")
        return

    try:
        # Search for unread bounce messages
        # "from:mailer-daemon" covers most standard bounces
        # "is:unread" ensures we process new ones
        query = "from:mailer-daemon is:unread"
        results = service.users().messages().list(userId="me", q=query).execute()
        messages = results.get("messages", [])

        if not messages:
            return

        user = db.users.find_one({"_id": user_id})
        daily_sent = user.get("daily_sent", 1)  # Avoid div by zero
        bounces_today = user.get("bounces_today", 0)

        for msg in messages:
            msg_id = msg["id"]
            try:
                full_msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
                
                # Extract failed email
                failed_email = extract_failed_email(full_msg)
                if not failed_email:
                    # Mark read anyway to avoid infinite loop
                    mark_as_read(service, msg_id)
                    continue
                
                # Determine bounce type
                is_hard_bounce = check_hard_bounce(full_msg)
                
                # Update System
                handle_bounce(user_id, failed_email, is_hard_bounce)
                
                # Update Stats
                bounces_today += 1
                
                # Mark as read
                mark_as_read(service, msg_id)

            except Exception as e:
                LOG.error(f"Error processing bounce message {msg_id} for user {user_id}: {e}")

        # Check threshold
        bounce_rate = bounces_today / max(daily_sent, 1)
        if bounce_rate > BOUNCE_THRESHOLD and daily_sent > 10:
             LOG.warning(f"Pause campaign for user {user_id} due to high bounce rate: {bounce_rate}")
             db.users.update_one({"_id": user_id}, {"$set": {"campaign_active": False, "campaign_paused_reason": "high_bounce_rate"}})
        
        # Update user stats
        db.users.update_one({"_id": user_id}, {"$set": {"bounces_today": bounces_today}})

    except HttpError as e:
        LOG.error(f"Gmail API error scanning bounces for {user_id}: {e}")
    except Exception as e:
        LOG.exception(f"Unexpected error in scan_user_bounces: {e}")

def extract_failed_email(msg_details):
    # Try 1: X-Failed-Recipients header
    payload = msg_details.get("payload", {})
    headers = payload.get("headers", [])
    
    for h in headers:
        if h["name"].lower() == "x-failed-recipients":
            return h["value"].strip()
            
    # Try 2: Parse snippet or body
    snippet = msg_details.get("snippet", "")
    # naive regex
    emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", snippet)
    if emails:
        # returns the first one found, rarely correct if multiple, but good enough for simple bounces
        return emails[0]
        
    return None

def check_hard_bounce(msg_details):
    snippet = msg_details.get("snippet", "").lower()
    for keyword in HARD_BOUNCE_KEYWORDS:
        if keyword in snippet:
            return True
    return False

def handle_bounce(user_id, email, is_hard_bounce):
    email = email.lower().strip()
    
    # Update global Recruiter health
    if is_hard_bounce:
        db.recruiters.update_one(
            {"email": email},
            {"$set": {"health": "dead", "last_bounce": datetime.utcnow()}, "$inc": {"bounceCount": 1}}
        )
        # Add to global suppression
        db.suppression.update_one(
            {"email": email},
            {"$set": {"email": email, "reason": "hard_bounce", "created_at": datetime.utcnow()}},
            upsert=True
        )
    else:
        # Soft bounce (e.g. out of office, quota full temporary)
        # Maybe mark risky?
        db.recruiters.update_one(
           {"email": email},
           {"$set": {"health": "risky", "last_bounce": datetime.utcnow()}, "$inc": {"bounceCount": 1}}
        )

    # Update Ledger status for THIS user
    # Find the most recent 'sent' or 'sending' entry for this email?
    # Actually we just want to mark any pending interaction as failed maybe?
    # Or just log it.
    
    # Find recruiter ID
    recruiter = db.recruiters.find_one({"email": email})
    if recruiter:
        db.user_recruiter_ledger.update_many(
            {"userId": user_id, "recruiterId": recruiter["_id"], "status": {"$in": ["sent", "sending"]}},
            {"$set": {"status": "bounced", "bounce_type": "hard" if is_hard_bounce else "soft"}}
        )

def mark_as_read(service, msg_id):
    try:
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
    except Exception as e:
        LOG.debug("Failed to mark message as read: %s", e)
