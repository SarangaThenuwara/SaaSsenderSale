import base64
import json
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from .db import db
from .utils import encrypt_bytes, decrypt_bytes, decrypt_b64_to_bytes, encrypt_bytes_to_b64

SCOPES = None
from .config import GMAIL_SCOPES
SCOPES = GMAIL_SCOPES

USERS = db.users

def get_gmail_service_for_user(user_id):
    """
    Builds a Gmail service for a user using stored base64 credentials and token.
    Refreshes token if needed and persists token back to DB.
    """
    user = USERS.find_one({"_id": user_id})
    if not user:
        raise ValueError("User not found")

    encrypted_credentials = user.get("credentials_base64")
    encrypted_token = user.get("token_base64")
    if not (encrypted_credentials and encrypted_token):
        raise ValueError("Missing credentials or token for user")

    # Decrypt: Stored string -> Encrypted bytes -> (Decrypted) B64 String
    # Note: If database values are NOT encrypted yet (migration/legacy), this might fail if we don't try/except
    # But for new code, we assume encryption. For safety, we can try decrypt, if it fails, assume plain b64.
    
    # Credentials
    try:
        credentials_b64_str = decrypt_b64_to_bytes(encrypted_credentials).decode("utf-8")
    except Exception:
        # Fallback for unencrypted data (if any)
        credentials_b64_str = encrypted_credentials

    # Token
    try:
        token_b64_str = decrypt_b64_to_bytes(encrypted_token).decode("utf-8")
    except Exception:
        token_b64_str = encrypted_token

    # Decode B64 to JSON
    try:
        client_info_json = base64.b64decode(credentials_b64_str).decode("utf-8")
        token_info_raw = base64.b64decode(token_b64_str).decode("utf-8")
    except Exception:
        raise ValueError("Failed to decode credentials/token from Base64")

    try:
        client_info = json.loads(client_info_json)
    except Exception:
        raise ValueError("Credentials must be a valid Base64 encoded JSON.")

    try:
        token_info = json.loads(token_info_raw)
    except Exception:
        # If not JSON, treat it as a raw token
        token_info = {"token": token_info_raw}

    # client_info may have keys under 'installed' or 'web'
    if client_info.get("type") == "service_account":
        raise ValueError("Service Account keys are not supported. Please use an OAuth 2.0 Client ID (JSON) for a User application.")
        
    client_section = client_info.get("installed") or client_info.get("web")
    if not client_section:
        raise ValueError("Invalid credentials JSON structure. key 'installed' or 'web' not found.")
        
    client_id = client_section.get("client_id")
    client_secret = client_section.get("client_secret")

    creds = Credentials(
        token=token_info.get("token"),
        refresh_token=token_info.get("refresh_token"),
        token_uri=token_info.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES
    )

    # refresh if expired
    try:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # persist refreshed token back to DB as ENCRYPTED base64 JSON
            new_token_json = creds.to_json()
            # 1. Base64 encode the JSON
            b64_str = base64.b64encode(new_token_json.encode()).decode()
            # 2. Encrypt the Base64 string
            encrypted_new_token = encrypt_bytes_to_b64(b64_str.encode())
            
            USERS.update_one({"_id": user_id}, {"$set": {"token_base64": encrypted_new_token}})
    except Exception as e:
        # mark user as needing reauth
        USERS.update_one({"_id": user_id}, {"$set": {"needs_reauth": True}})
        raise

    service = build("gmail", "v1", credentials=creds)
    return service