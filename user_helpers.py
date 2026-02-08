"""
Helpers for saving user metadata and CV reference in MongoDB,
and retrieving CV bytes from Backblaze using storage_b2.
Assumes `db` is a pymongo database object created elsewhere in your app.
"""
import base64
import os
import datetime
from typing import Optional
from pymongo import ReturnDocument
from storage_b2 import upload_cv_bytes, download_cv_bytes

# `db` should already exist in your app (from pymongo import MongoClient ...)
# Example in your main app: client = MongoClient(MONGODB_URI); db = client[MONGODB_DB]
from app import db  # adjust import depending on your structure

USERS_COL = db.get_collection("users")

def save_user_credentials(user_id, credentials_base64: str, token_base64: str):
    USERS_COL.update_one(
        {"_id": user_id},
        {"$set": {"credentials_base64": credentials_base64, "token_base64": token_base64}},
        upsert=True,
    )

def save_cv_for_user_b2(user_id, filename: str, file_bytes: bytes, content_type: str = "application/pdf"):
    """
    Upload CV bytes to B2 and store the object key and metadata in users collection.
    """
    key = upload_cv_bytes(file_bytes, filename, content_type=content_type)
    USERS_COL.update_one(
        {"_id": user_id},
        {"$set": {
            "cv_b2_key": key,
            "cv_filename": filename,
            "cv_content_type": content_type,
            "cv_uploaded_at": datetime.datetime.utcnow()
        }},
        upsert=True,
    )
    return key

def get_user_doc(user_id) -> Optional[dict]:
    return USERS_COL.find_one({"_id": user_id})

def get_cv_bytes_for_user(user_id) -> Optional[tuple]:
    """
    Returns (bytes, filename, content_type) or None if no CV.
    """
    user = get_user_doc(user_id)
    if not user:
        raise ValueError("User not found")
    key = user.get("cv_b2_key")
    if not key:
        return None
    data, content_type = download_cv_bytes(key)
    filename = user.get("cv_filename", "cv.pdf")
    return data, filename, content_type