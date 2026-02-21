from fastapi import Request, HTTPException, Depends
from .config import ADMIN_API_KEY
from .utils import get_csrf_token_from_request, validate_csrf_token
import uuid

def get_csrf_session_id(request: Request):
    """
    Extremely stable identity for CSRF.
    Priority: session_id > "anonymous-placeholder".
    """
    try:
        session = request.scope.get("session")
        if session:
            if session.get("session_id"):
                return session.get("session_id")
            if session.get("access_token"):
                # Use a prefix/suffix to avoid potential overlap with session_ids
                return f"token:{session.get('access_token')[:32]}"
    except Exception:
        pass
    
    return "anon-stable"

async def csrf_protect(request: Request):
    """
    FastAPI Dependency to enforce CSRF.
    Exempts requests using STATIC API KEYS (intended for programmatic access).
    Checks Header 'X-CSRF-Token' or Form 'csrf'.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # 1. Exempt Static API Keys (X-Admin-API-Key)
    api_key = request.headers.get("X-Admin-API-Key")
    if api_key and api_key == ADMIN_API_KEY:
        return

    # 2. Extract Token
    token = await get_csrf_token_from_request(request)
    
    # 3. Validate
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(token, sid):
        raise HTTPException(status_code=403, detail="CSRF validation failed. Token invalid or expired.")

from bson.objectid import ObjectId
from bson.errors import InvalidId

def parse_oid(oid_str: str) -> ObjectId:
    """
    Safely parse a string into a BSON ObjectId.
    Raises 400 Bad Request if the format is invalid.
    """
    try:
        return ObjectId(oid_str)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid ID format: '{oid_str}'. Must be a 24-character hex string.")
