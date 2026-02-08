"""
Per-user send worker (thread-based). Uses user's Gmail credentials stored in users collection.
Downloads CV bytes from B2 (via user_helpers.get_cv_bytes_for_user) and attaches to each mail.
This is a small, synchronous worker suitable for <=10 users; for larger scale replace with queue/worker.
"""
import threading
import time
import random
import datetime
import traceback
from app import db, add_log, SCOPES  # adjust imports for your app structure
from user_helpers import get_user_doc, get_cv_bytes_for_user
from gmail_helpers import get_gmail_service_for_user  # use the get_gmail_service_for_user function from earlier snippet
from create_message_bytes import create_message
from googleapiclient.errors import HttpError

RECIPIENTS_COL = db.get_collection("recipients")
USERS_COL = db.get_collection("users")

def send_for_user(user_id):
    add_log(f"Starting send worker for user {user_id}")
    user = get_user_doc(user_id)
    if not user:
        add_log(f"User {user_id} not found")
        return

    try:
        service = get_gmail_service_for_user(user_id, SCOPES)
    except Exception as e:
        add_log(f"Failed to init Gmail for user {user_id}: {e}")
        return

    sender = "me"
    subject_template = user.get("subject_template", "Hi {first_name},")
    body_template = user.get("body_template", "<p>Hi {first_name},</p>")
    daily_limit = user.get("daily_limit", 240)

    # reset daily counter as needed
    today_str = str(datetime.date.today())
    if user.get("last_reset_date") != today_str:
        USERS_COL.update_one({"_id": user_id}, {"$set": {"daily_sent": 0, "last_reset_date": today_str}})

    # get current counter
    user = get_user_doc(user_id)
    daily_sent = user.get("daily_sent", 0)

    while True:
        # atomically find one pending recipient for this user
        recipient = RECIPIENTS_COL.find_one_and_update(
            {"user_id": user_id, "status": "Pending"},
            {"$set": {"status": "InProgress", "updated_at": datetime.datetime.utcnow()}},
            sort=[("created_at", 1)],
            return_document=False
        )
        if not recipient:
            add_log(f"No pending recipients for user {user_id}")
            break

        if daily_sent >= daily_limit:
            add_log(f"User {user_id} reached daily limit ({daily_limit}). Stopping.")
            # mark back to Pending so user can resume later
            RECIPIENTS_COL.update_one({"_id": recipient["_id"]}, {"$set": {"status": "Pending"}})
            break

        recipient_email = recipient.get("email")
        first_name = recipient_email.split("@")[0].capitalize()
        subject = subject_template.format(first_name=first_name)
        html_body = body_template.format(first_name=first_name)

        # fetch CV bytes from B2 (if present)
        cv_info = get_cv_bytes_for_user(user_id)
        attachment_bytes = None
        attachment_name = None
        if cv_info:
            attachment_bytes, attachment_name, _ct = cv_info[0], cv_info[1], cv_info[2]  # get_cv_bytes_for_user returns (data, filename, content_type)
            # but user_helpers returns (data, filename, content_type) — adjust accordingly
            attachment_bytes = cv_info[0]
            attachment_name = cv_info[1]

        try:
            msg = create_message(sender, recipient_email, subject, html_body, attachment_bytes=attachment_bytes, attachment_name=attachment_name or "cv.pdf")
            service.users().messages().send(userId='me', body=msg).execute()
            RECIPIENTS_COL.update_one({"_id": recipient["_id"]}, {"$set": {"status": "Sent", "sent_at": datetime.datetime.utcnow()}})
            daily_sent += 1
            USERS_COL.update_one({"_id": user_id}, {"$set": {"daily_sent": daily_sent}})
            add_log(f"Sent to {recipient_email} for user {user_id}")
        except HttpError as e:
            RECIPIENTS_COL.update_one({"_id": recipient["_id"]}, {"$set": {"status": "Failed", "last_error": str(e)}})
            add_log(f"HTTP error sending to {recipient_email} for user {user_id}: {e}")
        except Exception as e:
            RECIPIENTS_COL.update_one({"_id": recipient["_id"]}, {"$set": {"status": "Failed", "last_error": str(e)}})
            add_log(f"Error sending to {recipient_email} for user {user_id}: {e}\n{traceback.format_exc()}")

        # polite randomized delay to avoid being too bursty
        time.sleep(random.randint(60, 300))

def start_user_send_thread(user_id):
    t = threading.Thread(target=send_for_user, args=(user_id,))
    t.daemon = True
    t.start()
    return t