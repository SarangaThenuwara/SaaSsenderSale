import datetime
import random
import time
import logging
from bson.objectid import ObjectId

from .celery_app import celery_app
from .db import db
from .user_helpers import get_cv_bytes_for_user, get_user, get_user_daily_limit
from .gmail_helpers import get_gmail_service_for_user
from .create_message import create_message
from .utils import parse_spintax
from pymongo import ReturnDocument
from googleapiclient.errors import HttpError

LOG = logging.getLogger(__name__)

RECIPIENTS = db.recipients
USERS = db.users

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_batch_for_user(self, user_id, batch_size=10):
    """
    Claim up to batch_size assigned recipients for user_id and send them.
    Uses the User Recruiter Ledger and Recruiters collection.
    """
    if isinstance(user_id, str):
        try:
            user_id = ObjectId(user_id)
        except Exception:
            pass

    user = USERS.find_one({"_id": user_id})
    if not user:
        return {"error": "user not found"}

    if user.get("is_blocked") or user.get("is_deleted"):
        return {"error": "user blocked or deleted"}

    if not user.get("campaign_active"):
        return {"status": "campaign inactive"}
    
    # Get active campaign ID (default or specific)
    active_campaign_id = user.get("active_campaign_id", "default")

    if not user.get("credentials_base64") or not user.get("token_base64"):
        return {"error": "missing credentials"}

    if user.get("needs_reauth"):
        return {"error": "user needs reauth"}

    daily_limit = get_user_daily_limit(user)
    daily_sent = user.get("daily_sent", 0)
    
    if daily_sent >= daily_limit:
        return {"status": "daily limit reached"}

    sent_count = 0
    # Process batch
    for _ in range(batch_size):
        # 1. Refresh User Settings to pick up live changes (CV/Templates/Stop signals)
        user = USERS.find_one({"_id": user_id})
        if not user or user.get("is_blocked") or user.get("is_deleted") or not user.get("campaign_active"):
            break
            
        if user.get("daily_sent", 0) >= get_user_daily_limit(user):
            break

        # 2. Pick a pending job from the ledger
        active_campaign_id = user.get("active_campaign_id", "default")
        ledger_query = {
            "userId": user_id, 
            "status": "pending",
            "campaignId": active_campaign_id 
        }
        
        # Atomically lock the job
        job = db.user_recruiter_ledger.find_one_and_update(
            ledger_query,
            {"$set": {"status": "sending", "lastAttempt": datetime.datetime.utcnow()}},
            sort=[("lastAttempt", 1)] # Fair queue or priority? LastAttempt usage?
        )
        
        if not job:
            break

        recruiter_id = job["recruiterId"]
        recruiter = db.recruiters.find_one({"_id": recruiter_id})
        
        # 2. Validation Checks
        if not recruiter:
            db.user_recruiter_ledger.update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "error": "recruiter missing"}})
            continue
            
        email = recruiter.get("email")
        if not email:
            db.user_recruiter_ledger.update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "error": "email missing"}})
            continue

        # Check Health
        if recruiter.get("health") == "dead":
            db.user_recruiter_ledger.update_one({"_id": job["_id"]}, {"$set": {"status": "skipped", "error": "recruiter dead"}})
            continue

        # Check Global Suppression
        if db.suppression.find_one({"email": email}):
            db.user_recruiter_ledger.update_one({"_id": job["_id"]}, {"$set": {"status": "skipped", "error": "suppressed"}})
            continue

        # 3. Preparation (Prioritize snapshot for locked assets)
        snapshot = user.get("campaign_snapshot")
        if snapshot:
            cv_key = snapshot.get("cv_key")
            cv_name = snapshot.get("cv_filename")
            # Randomly select from snapshot email templates
            snap_templates = snapshot.get("email_templates", [])
            if snap_templates:
                chosen = random.choice(snap_templates)
                subject = chosen.get("subject", "[Job Title] - {first_name}")
                body = chosen.get("body", "<p>{Dear|Hi} [Recruiter Name],</p><p>I am writing to express my interest in the [Job Title] role.</p>")
            else:
                # Backward compat: use old single subject/body
                subject = snapshot.get("subject", "Regarding the job opening")
                body = snapshot.get("body", "<p>Hi,</p><p>I'm interested in the position.</p>")
        else:
            cv_key = user.get("cv_b2_key")
            cv_name = user.get("cv_filename")
            # Randomly select from user email templates
            user_templates = user.get("email_templates", [])
            if user_templates:
                chosen = random.choice(user_templates)
                subject = chosen.get("subject", "[Job Title] - {first_name}")
                body = chosen.get("body", "<p>{Dear|Hi} [Recruiter Name],</p><p>I am writing to express my interest in the [Job Title] role.</p>")
            else:
                # Backward compat: use old single subject/body
                subject = user.get("subject_template", "[Job Title] - {first_name}")
                body = user.get("body_template", "<p>{Dear|Hi} [Recruiter Name],</p><p>I am writing to express my interest in the [Job Title] role.</p>")

        # 3.1. Apply Spintax and Placeholders
        first_name = (user.get("username") or "User").split()[0].capitalize()
        subject = parse_spintax(subject).format(first_name=first_name)
        body = parse_spintax(body).format(first_name=first_name)

        # Fetch CV bytes using the key from snapshot (or user current if no snapshot)
        cv_info = get_cv_bytes_for_user(user_id, key=cv_key, filename=cv_name)
        attachment_bytes = None
        attachment_name = None
        if cv_info:
            attachment_bytes, attachment_name, _ct = cv_info

        # 4. Sending
        try:
            service = get_gmail_service_for_user(user_id)
            msg = create_message("me", email, subject, body, attachment_bytes=attachment_bytes, attachment_name=attachment_name or "cv.pdf")
            service.users().messages().send(userId="me", body=msg).execute()
            
            # Success
            db.user_recruiter_ledger.update_one({"_id": job["_id"]}, {"$set": {"status": "sent", "sent_at": datetime.datetime.utcnow()}})
            USERS.update_one({"_id": user_id}, {"$inc": {"daily_sent": 1}})
            sent_count += 1
            
        except HttpError as e:
            LOG.exception("Gmail API HttpError sending to %s: %s", email, e)
            db.user_recruiter_ledger.update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "error": str(e)}})
            # If hard bounce indicated in API error (rare, usually separate), handle it.
            # Usually bounces come via standard bounce mails, captured by another worker.
            
        except Exception as e:
            LOG.exception("Unexpected error sending to %s: %s", email, e)
            db.user_recruiter_ledger.update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "error": str(e)}})

        # 6. Throttling
        time_sleep = random.randint(10, 30)
        time.sleep(time_sleep)

    return {"sent": sent_count}

@celery_app.task
def reset_daily_limits():
    """
    Resets daily_sent to 0 for all users.
    """
    LOG.info("Global daily limit reset started.")
    res = USERS.update_many({}, {"$set": {"daily_sent": 0}})
    return {"reset_count": res.modified_count}

@celery_app.task
def purge_deleted_users():
    """
    Permanently deletes users who have been soft-deleted for more than 90 days.
    """
    threshold = datetime.datetime.utcnow() - datetime.timedelta(days=90)
    to_delete = list(USERS.find({"is_deleted": True, "deleted_at": {"$lt": threshold}}))
    count = 0
    for u in to_delete:
        USERS.delete_one({"_id": u["_id"]})
        # Cleanup ledger?
        db.user_recruiter_ledger.delete_many({"userId": u["_id"]})
        count += 1
    return {"purged_count": count}


def send_single_message_for_user(user_id, to_email, subject_override=None, body_override=None):
    """
    Send a single test message for the given user using that user's Gmail credentials.
    Does NOT increment daily_sent or mark any recipient documents.
    user_id may be an ObjectId or string.
    Returns a dict with 'ok': True/False and provider response or error.
    """
    if isinstance(user_id, str):
        try:
            user_id = ObjectId(user_id)
        except Exception:
            pass

    user = USERS.find_one({"_id": user_id})
    if not user:
        raise ValueError("User not found")

    if user.get("is_blocked"):
        raise RuntimeError("User is blocked")

    if user.get("needs_reauth"):
        raise RuntimeError("User needs re-authentication")

    # Build subject and body from overrides or user templates
    first_name = (user.get("username") or "User").split()[0].capitalize()
    
    subject = subject_override if subject_override is not None else user.get("subject_template", "Hi {first_name}")
    body = body_override if body_override is not None else user.get("body_template", "<p>Hi {first_name}</p>")

    # Apply Spintax first, then placeholders
    subject = parse_spintax(subject).format(first_name=first_name)
    body = parse_spintax(body).format(first_name=first_name)

    cv_info = get_cv_bytes_for_user(user_id)
    attachment_bytes = None
    attachment_name = None
    if cv_info:
        attachment_bytes, attachment_name, _ct = cv_info

    try:
        service = get_gmail_service_for_user(user_id)
        msg = create_message("me", to_email, subject, body, attachment_bytes=attachment_bytes, attachment_name=attachment_name or "cv.pdf")
        resp = service.users().messages().send(userId="me", body=msg).execute()
        return {"ok": True, "response": resp}
    except HttpError as e:
        LOG.exception("Gmail API error during test send: %s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        LOG.exception("Unexpected error during test send: %s", e)
        return {"ok": False, "error": str(e)}