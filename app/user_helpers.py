import base64
import datetime
from typing import Optional
from .db import db
from .storage_b2 import upload_cv_bytes, download_cv_bytes
from .utils import encrypt_bytes, decrypt_bytes

USERS = db.users

def create_or_update_user(username: str, email: str, daily_limit: int = 240) -> dict:
    now = datetime.datetime.utcnow()
    res = USERS.find_one_and_update(
        {"username": username},
        {"$setOnInsert": {"created_at": now},
         "$set": {"email": email, "daily_limit": daily_limit, "active": True, "is_blocked": False, "is_deleted": False}},
        upsert=True,
        return_document=True
    )
    if not res:
        res = USERS.find_one({"username": username})
    return res

def save_credentials_base64(user_id, credentials_base64: str, token_base64: str):
    """
    Encrypt and store Gmail API credentials.
    """
    from .utils import encrypt_bytes_to_b64
    
    # Encrypt both before storing
    encrypted_creds = encrypt_bytes_to_b64(credentials_base64.encode())
    encrypted_token = encrypt_bytes_to_b64(token_base64.encode())
    
    USERS.update_one({"_id": user_id}, {"$set": {
        "credentials_base64": encrypted_creds, 
        "token_base64": encrypted_token,
        "credentials_valid": True,  # Mark as done
        "needs_reauth": False
    }})

def save_templates(user_id, subject_template: str, body_template: str):
    now = datetime.datetime.utcnow()
    # 1. Add to history
    USERS.update_one(
        {"_id": user_id},
        {"$push": {
            "template_history": {
                "subject": subject_template,
                "body": body_template,
                "timestamp": now
            }
        }}
    )
    # 2. Update current
    USERS.update_one({"_id": user_id}, {"$set": {"subject_template": subject_template, "body_template": body_template}})

def save_cv_b2(user_id, filename: str, file_bytes: bytes, content_type: str = "application/pdf"):
    now = datetime.datetime.utcnow()
    key = upload_cv_bytes(file_bytes, filename, content_type=content_type, user_id=str(user_id))
    
    # 1. Add to version history
    USERS.update_one(
        {"_id": user_id},
        {"$push": {
            "cv_history": {
                "key": key,
                "filename": filename,
                "content_type": content_type,
                "timestamp": now
            }
        }}
    )
    
    # 2. Update current
    USERS.update_one({"_id": user_id}, {"$set": {
        "cv_b2_key": key,
        "cv_filename": filename,
        "cv_content_type": content_type,
        "cv_uploaded_at": now
    }})
    return key

def get_user(user_id) -> Optional[dict]:
    return USERS.find_one({"_id": user_id})

def get_cv_bytes_for_user(user_id, key: Optional[str] = None, filename: Optional[str] = None):
    if not key:
        user = get_user(user_id)
        if not user:
            return None
        key = user.get("cv_b2_key")
        filename = user.get("cv_filename", "cv.pdf")
        
    if not key:
        return None
        
    try:
        data, content_type = download_cv_bytes(key)
        return data, filename or "cv.pdf", content_type
    except Exception:
        return None

def get_user_daily_limit(user: dict) -> int:
    """
    Determines the daily sending limit based on email warmup and enrollment date.
    All users: Up to 240 emails/day, starting with a warmup phase.
    
    Warmup Schedule (Linear):
    Day 1: 20 emails
    Day 2: 40 emails
    ...
    Day 12: 240 emails (Full capacity)
    """
    if not user:
        return 20
    
    # 1. Base potential limit from user record
    max_limit = user.get("daily_limit", 240)
    
    # 2. Calculate Warmup Limit
    created_at = user.get("created_at")
    if not created_at:
        # Fallback if created_at is missing for some reason
        return max_limit
        
    now = datetime.datetime.utcnow()
    # Days since signup (0-indexed, so today is day 0)
    days_since_signup = (now - created_at).days
    
    # Warmup formula: 20 base + (20 * days_since_signup)
    warmup_limit = 20 + (days_since_signup * 20)
    
    # 3. Return the lesser of the warmup limit or the user's max daily limit
    return min(warmup_limit, max_limit)