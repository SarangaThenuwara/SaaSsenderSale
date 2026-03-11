import base64
import secrets
from typing import Optional
from itsdangerous import URLSafeTimedSerializer
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import logging

from .config import FERNET_KEY, SECRET_KEY

# Initialize Encryption Keys - Enterprise Requirement: KEY MUST BE PRESENT
_f: Optional[Fernet] = None
_aesgcm: Optional[AESGCM] = None

if FERNET_KEY:
    try:
        key = FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY
        _f = Fernet(key)
        
        try:
            raw_key = base64.urlsafe_b64decode(key)
            if len(raw_key) == 32:
                _aesgcm = AESGCM(raw_key)
            else:
                import hashlib
                _aesgcm = AESGCM(hashlib.sha256(key).digest())
        except Exception:
            import hashlib
            _aesgcm = AESGCM(hashlib.sha256(key).digest())
            
    except Exception as e:
        logging.warning("Failed to initialize Encryption keys: %s", e)

def encrypt_bytes(b: bytes) -> bytes:
    """
    Encrypt bytes with AES-256-GCM. 
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _aesgcm:
        raise RuntimeError("ENCRYPTION_FAILURE: AES-256-GCM key not configured.")
    nonce = secrets.token_bytes(12)
    ciphertext = _aesgcm.encrypt(nonce, b, None)
    return nonce + ciphertext

def decrypt_bytes(b: bytes) -> bytes:
    """
    Decrypt bytes with AES-256-GCM or fallback to Fernet.
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _aesgcm or not _f:
        raise RuntimeError("DECRYPTION_FAILURE: Encryption key not configured.")
    if isinstance(b, str):
        b = b.encode()
        
    try:
        # Check if legacy Fernet (which uses urlsafe base64, starts with 'gAAAA' usually)
        if b.startswith(b"gAAAAA"):
            return _f.decrypt(b)
        else:
            nonce = b[:12]
            ciphertext = b[12:]
            return _aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        # Fallback in case the non-v2 bytes were just pure Fernet bytes.
        return _f.decrypt(b)

def encrypt_bytes_to_b64(b: bytes) -> str:
    """
    Return encrypted bytes as a base64-encoded string, using AES-256-GCM.
    Prefix with 'v2:' to distinguish new AES-256-GCM encryptions.
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _aesgcm:
        raise RuntimeError("ENCRYPTION_FAILURE: AES-256-GCM key not configured. Sensitive data cannot be stored.")
    enc_bytes = encrypt_bytes(b)
    return "v2:" + base64.urlsafe_b64encode(enc_bytes).decode('ascii')

def decrypt_b64_to_bytes(s: str) -> bytes:
    """
    Inverse of encrypt_bytes_to_b64. Uses AES-256-GCM if prefixed with 'v2:',
    otherwise falls back to legacy Fernet AES-128.
    Enterprise Policy: Fails if encryption is not configured.
    """
    if not _aesgcm or not _f:
        raise RuntimeError("DECRYPTION_FAILURE: Encryption key not configured.")
        
    if s.startswith("v2:"):
        actual_b64 = s[3:]
        raw_bytes = base64.urlsafe_b64decode(actual_b64)
        nonce = raw_bytes[:12]
        ciphertext = raw_bytes[12:]
        return _aesgcm.decrypt(nonce, ciphertext, None)
    else:
        # Legacy Fernet format
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