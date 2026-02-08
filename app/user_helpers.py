import base64
import datetime
from typing import Optional
from .db import db
from .storage_b2 import upload_cv_bytes, download_cv_bytes
from .utils import encrypt_bytes, decrypt_bytes

USERS = db.users

def create_or_update_user(username: str, email: str, daily_limit: int = 300) -> dict:
    now = datetime.datetime.utcnow()
    res = USERS.find_one_and_update(
        {"username": username},
        {"$setOnInsert": {"created_at": now},
         "$set": {"email": email, "daily_limit": daily_limit, "active": True}},
        upsert=True,
        return_document=True
    )
    if not res:
        res = USERS.find_one({"username": username})
    return res

def save_credentials_base64(user_id, credentials_base64: str, token_base64: str):
    # Optionally encrypt token_base64 before storing
    USERS.update_one({"_id": user_id}, {"$set": {"credentials_base64": credentials_base64, "token_base64": token_base64}})

def save_templates(user_id, subject_template: str, body_template: str):
    USERS.update_one({"_id": user_id}, {"$set": {"subject_template": subject_template, "body_template": body_template}})

def save_cv_b2(user_id, filename: str, file_bytes: bytes, content_type: str = "application/pdf"):
    key = upload_cv_bytes(file_bytes, filename, content_type=content_type)
    USERS.update_one({"_id": user_id}, {"$set": {
        "cv_b2_key": key,
        "cv_filename": filename,
        "cv_content_type": content_type,
        "cv_uploaded_at": datetime.datetime.utcnow()
    }})
    return key

def get_user(user_id) -> Optional[dict]:
    return USERS.find_one({"_id": user_id})

def get_cv_bytes_for_user(user_id):
    user = get_user(user_id)
    if not user:
        return None
    key = user.get("cv_b2_key")
    if not key:
        return None
    data, content_type = download_cv_bytes(key)
    filename = user.get("cv_filename", "cv.pdf")
    return data, filename, content_type