import base64
from typing import Optional
from itsdangerous import URLSafeTimedSerializer
from cryptography.fernet import Fernet

from .config import FERNET_KEY, SECRET_KEY

# Initialize Fernet if key provided
_f: Optional[Fernet] = None
if FERNET_KEY:
    key = FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY
    _f = Fernet(key)

def encrypt_bytes(b: bytes) -> bytes:
    """
    Backwards-compatible: encrypt bytes with Fernet if configured,
    otherwise return original bytes.
    """
    if not _f:
        return b
    return _f.encrypt(b)

def decrypt_bytes(b: bytes) -> bytes:
    """
    Backwards-compatible: decrypt bytes with Fernet if configured,
    otherwise return original bytes.
    Accepts either bytes or (if callers stored base64 text) a str encoded to bytes.
    """
    if not _f:
        return b
    if isinstance(b, str):
        b = b.encode()
    return _f.decrypt(b)

# Helpers that encode to/from base64 strings (useful for storing in JSON/DB)
def encrypt_bytes_to_b64(b: bytes) -> str:
    """
    Return encrypted bytes as a base64-encoded string if Fernet configured,
    otherwise return plain base64-encoded string of original bytes.
    """
    if _f:
        token = _f.encrypt(b)
        return token.decode()
    return base64.b64encode(b).decode()

def decrypt_b64_to_bytes(s: str) -> bytes:
    """
    Inverse of encrypt_bytes_to_b64.
    """
    if _f:
        return _f.decrypt(s.encode())
    return base64.b64decode(s.encode())

# CSRF helpers using itsdangerous, tied to SECRET_KEY
_serializer = URLSafeTimedSerializer(SECRET_KEY)

def generate_csrf_token(session_id: str) -> str:
    """
    Produce a signed token tied to session_id.
    """
    return _serializer.dumps(session_id, salt="csrf-token")

def validate_csrf_token(token: str, session_id: str, max_age: int = 3600) -> bool:
    """
    Validate a CSRF token produced by generate_csrf_token.
    """
    try:
        val = _serializer.loads(token, salt="csrf-token", max_age=max_age)
        return val == session_id
    except Exception:
        return False