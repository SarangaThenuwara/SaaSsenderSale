import threading
import random
import time

# send loop for one user
def send_for_user(user_id):
    add_log(f"Starting send worker for user {user_id}")
    try:
        service = get_gmail_service_for_user(user_id, SCOPES)
    except Exception as e:
        add_log(f"Failed to init Gmail for user {user_id}: {e}")
        return

    user = get_user_doc(user_id)
    sender = "me"  # when using Gmail client of user, 'me' refers to that account
    # load user's templates and limit
    subject_template = user.get("subject_template", "Hi {first_name}")
    body_template = user.get("body_template", "<p>Hi {first_name}</p>")
    daily_limit = user.get("daily_limit", 300)

    # implement per-user daily counter
    today = datetime.date.today()
    if user.get("last_reset_date") != str(today):
        db.get_collection("users").update_one({"_id": user_id}, {"$set": {"daily_sent": 0, "last_reset_date": str(today)}})
    daily_sent = user.get("daily_sent", 0)

    while True:
        # query one pending recipient for this user and atomically mark InProgress
        recipient = db.get_collection("recipients").find_one_and_update(
            {"user_id": user_id, "status": "Pending"},
            {"$set": {"status": "InProgress", "updated_at": datetime.datetime.utcnow()}},
            sort=[("created_at", 1)]
        )
        if not recipient:
            add_log(f"No more pending recipients for user {user_id}")
            break

        if daily_sent >= daily_limit:
            add_log(f"User {user_id} reached daily limit {daily_limit}")
            break

        recipient_email = recipient.get("email")
        first_name = recipient_email.split("@")[0].capitalize()
        subject = subject_template.format(first_name=first_name)
        html_body = body_template.format(first_name=first_name)

        try:
            attachment_bytes = None
            cv_file_id = user.get("cv_file_id")
            if cv_file_id:
                attachment_bytes = get_cv_bytes(cv_file_id)
            # build message - reuse your create_message but accept bytes for attachment
            msg = create_message(sender, recipient_email, subject, html_body, attachment_bytes=attachment_bytes, attachment_name="cv.pdf")
            send_message(service, 'me', msg)
            db.get_collection("recipients").update_one({"_id": recipient["_id"]}, {"$set": {"status": "Sent", "sent_at": datetime.datetime.utcnow()}})
            daily_sent += 1
            db.get_collection("users").update_one({"_id": user_id}, {"$set": {"daily_sent": daily_sent}})
            add_log(f"Sent email for user {user_id} to {recipient_email}")
        except Exception as e:
            db.get_collection("recipients").update_one({"_id": recipient["_id"]}, {"$set": {"status": "Failed", "last_error": str(e)}})
            add_log(f"Failed sending for {user_id} to {recipient_email}: {e}")

        time.sleep(random.randint(60, 300))  # keep delays simple

# To trigger from UI:
def start_user_send_thread(user_id):
    t = threading.Thread(target=send_for_user, args=(user_id,))
    t.start()
    return "Started"