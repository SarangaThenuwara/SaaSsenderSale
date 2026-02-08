import datetime
import random
import time
import logging
from bson.objectid import ObjectId

from .celery_app import celery_app
from .db import db
from .user_helpers import get_cv_bytes_for_user, get_user
from .gmail_helpers import get_gmail_service_for_user
from .create_message import create_message
from pymongo import ReturnDocument
from googleapiclient.errors import HttpError

LOG = logging.getLogger(__name__)

RECIPIENTS = db.recipients
USERS = db.users

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_batch_for_user(self, user_id, batch_size=10):
    """
    Claim up to batch_size assigned recipients for user_id and send them.
    """
    # Accept both ObjectId and string
    if isinstance(user_id, str):
        try:
            user_id = ObjectId(user_id)
        except Exception:
            pass

    user = USERS.find_one({"_id": user_id})
    if not user:
        LOG.error("User not found in send_batch_for_user: %s", user_id)
        return {"error": "user not found"}

    if not user.get("campaign_active"):
        LOG.info("Campaign not active for user %s, skipping.", user_id)
        return {"status": "campaign inactive"}

    if not user.get("credentials_base64") or not user.get("token_base64"):
        LOG.warning("Missing credentials/token for user %s, skipping.", user_id)
        return {"error": "missing credentials"}

    if user.get("needs_reauth"):
        LOG.warning("User needs reauth, skipping sends: %s", user_id)
        return {"error": "user needs reauth"}

    # Check Subscription
    from .db import db
    settings = db.settings.find_one({"_id": "global"}) or {}
    if settings.get("payment_gateway_enabled", False):
         # Admin bypass
         if user.get("role") != "admin":
             expires_at = user.get("subscription_expires_at")
             is_paid = user.get("is_paid")
             if not is_paid or not expires_at or expires_at < datetime.datetime.utcnow():
                 LOG.info("Subscription expired for user %s", user_id)
                 return {"status": "subscription expired"}


    daily_limit = user.get("daily_limit", 240)
    daily_sent = user.get("daily_sent", 0)
    if daily_sent >= daily_limit:
        LOG.info("Daily limit reached for user %s", user_id)
        return {"status": "daily limit reached"}

    sent = 0
    for _ in range(batch_size):
        r = RECIPIENTS.find_one_and_update(
            {"assigned_to": user_id, "status": "Assigned"},
            {"$set": {"status": "InProgress", "started_at": datetime.datetime.utcnow()}},
            sort=[("assigned_at", 1)],
            return_document=ReturnDocument.AFTER
        )
        if not r:
            break

        recipient_email = r.get("email")
        first_name = (r.get("name") or recipient_email.split("@")[0]).split()[0].capitalize()
        subject_template = user.get("subject_template", "Hi {first_name}")
        body_template = user.get("body_template", "<p>Hi {first_name}</p>")
        subject = subject_template.format(first_name=first_name)
        body = body_template.format(first_name=first_name)

        cv_info = get_cv_bytes_for_user(user_id)
        attachment_bytes = None
        attachment_name = None
        if cv_info:
            attachment_bytes, attachment_name, _ct = cv_info

        try:
            service = get_gmail_service_for_user(user_id)
            msg = create_message("me", recipient_email, subject, body, attachment_bytes=attachment_bytes, attachment_name=attachment_name or "cv.pdf")
            service.users().messages().send(userId="me", body=msg).execute()
            RECIPIENTS.update_one({"_id": r["_id"]}, {"$set": {"status": "Sent", "sent_at": datetime.datetime.utcnow()}})
            USERS.update_one({"_id": user_id}, {"$inc": {"daily_sent": 1}})
            sent += 1
        except HttpError as e:
            LOG.exception("Gmail API HttpError sending to %s: %s", recipient_email, e)
            RECIPIENTS.update_one({"_id": r["_id"]}, {"$set": {"status": "Failed", "last_error": str(e)}})
        except Exception as e:
            LOG.exception("Unexpected error sending to %s: %s", recipient_email, e)
            RECIPIENTS.update_one({"_id": r["_id"]}, {"$set": {"status": "Failed", "last_error": str(e)}})

        # polite delay between sends to avoid rapid bursts; randomized small delay
        time_sleep = random.randint(10, 30)
        time.sleep(time_sleep)

        # enforce per-user daily limit mid-batch
        user = USERS.find_one({"_id": user_id})
        if user.get("daily_sent", 0) >= daily_limit:
            break

    return {"sent": sent}

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

    if user.get("needs_reauth"):
        raise RuntimeError("User needs re-authentication")

    # Build subject and body from overrides or user templates
    first_name = (user.get("username") or "User").split()[0].capitalize()
    subject_template = user.get("subject_template", "Hi {first_name}")
    body_template = user.get("body_template", "<p>Hi {first_name}</p>")
    subject = subject_override if subject_override is not None else subject_template.format(first_name=first_name)
    body = body_override if body_override is not None else body_template.format(first_name=first_name)

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