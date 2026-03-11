import base64
from typing import Optional
from itsdangerous import URLSafeTimedSerializer
from cryptography.fernet import Fernet

from .config import FERNET_KEY, SECRET_KEY

# Initialize Fernet - Enterprise Requirement: KEY MUST BE PRESENT
_f: Optional[Fernet] = None
if FERNET_KEY:
    try:
        key = FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY
        _f = Fernet(key)
    except Exception as e:
        import logging
        logging.warning("Failed to initialize Fernet: %s", e)

def encrypt_bytes(b: bytes) -> bytes:
    """
    Encrypt bytes with Fernet. 
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _f:
        raise RuntimeError("ENCRYPTION_FAILURE: Fernet key not configured.")
    return _f.encrypt(b)

def decrypt_bytes(b: bytes) -> bytes:
    """
    Decrypt bytes with Fernet.
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _f:
        raise RuntimeError("DECRYPTION_FAILURE: Fernet key not configured.")
    if isinstance(b, str):
        b = b.encode()
    return _f.decrypt(b)

def encrypt_bytes_to_b64(b: bytes) -> str:
    """
    Return encrypted bytes as a base64-encoded string.
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _f:
        raise RuntimeError("ENCRYPTION_FAILURE: Fernet key not configured. Sensitive data cannot be stored.")
    token = _f.encrypt(b)
    return token.decode()

def decrypt_b64_to_bytes(s: str) -> bytes:
    """
    Inverse of encrypt_bytes_to_b64.
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _f:
        raise RuntimeError("DECRYPTION_FAILURE: Fernet key not configured.")
    return _f.decrypt(s.encode())

# CSRF helpers using itsdangerous, tied to SECRET_KEY
_serializer = URLSafeTimedSerializer(SECRET_KEY)

def generate_csrf_token(session_id: str) -> str:
    """
    Produce a signed token tied to session_id.
    """
    return _serializer.dumps(session_id, salt="csrf-token")

def validate_csrf_token(token: str, session_id: str, max_age: int = 900) -> bool:
    """
    Validate a CSRF token produced by generate_csrf_token.
    Supports both literal tokens and serialized objects if needed.
    """
    if not token or not session_id:
        return False
    try:
        val = _serializer.loads(token, salt="csrf-token", max_age=max_age)
        return val == session_id
    except Exception:
        return False

async def get_csrf_token_from_request(request):
    """
    Extracts CSRF token from Form field OR X-CSRF-Token header.
    """
    # 1. Check Header (Preferred for AJAX)
    header_token = request.headers.get("X-CSRF-Token")
    if header_token:
        return header_token
    
    # 2. Check Form Data
    try:
        form = await request.form()
        return form.get("csrf")
    except Exception as e:
        import logging
        logging.debug("Could not parse form for csrf: %s", e)
    # 3. Check JSON Body (Fallback)
    try:
        body = await request.json()
        return body.get("csrf")
    except Exception as e:
        import logging
        logging.debug("Could not parse json for csrf: %s", e)
        
    return None

def parse_spintax(text: str) -> str:
    """
    Randomly selects variations in curly braces {Hi|Hello|Hey} to provide 
    natural text variation and avoid spam fingerprinting.
    Only triggers if at least one '|' is present to avoid breaking {placeholders}.
    """
    import re
    import secrets
    if not text:
        return ""
        
    # Pattern looks for { ... | ... }
    pattern = re.compile(r"\{([^{}]*\|[^{}]*)\}")
    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split('|')
        text = text[:match.start()] + secrets.choice(options) + text[match.end():]
    return text