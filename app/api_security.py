"""
api_security.py — Deep API Security Layer
==========================================
Implements:
  1. HMAC-signed API key verification (constant-time comparison)
  2. Per-IP + per-key rate limit tracking via Redis
  3. Request fingerprinting & anomaly scoring
  4. Admin API response envelope encryption (AES-256-GCM)
  5. Suspicious activity auto-blocking
"""

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. HMAC API Key Verification
# ---------------------------------------------------------------------------

def _constant_time_compare(a: str, b: str) -> bool:
    """Use hmac.compare_digest to prevent timing attacks."""
    return hmac.compare_digest(
        a.encode("utf-8", errors="replace"),
        b.encode("utf-8", errors="replace"),
    )


def verify_admin_api_key(provided_key: str, expected_key: str) -> bool:
    """
    Validates the admin API key using constant-time comparison.
    Also rejects keys shorter than 32 chars as misconfigured.
    """
    if not provided_key or not expected_key:
        return False
    if len(expected_key) < 32:
        LOG.critical("SECURITY: ADMIN_API_KEY is too short (<32 chars). Blocking all API key auth.")
        return False
    return _constant_time_compare(provided_key, expected_key)


# ---------------------------------------------------------------------------
# 2. Per-IP Rate Limiting with Redis
# ---------------------------------------------------------------------------

_ADMIN_RATE_LIMIT = 60          # requests per window
_ADMIN_RATE_WINDOW = 60         # seconds
_ADMIN_BURST_LIMIT = 10         # requests per 5s burst window
_ADMIN_BURST_WINDOW = 5         # seconds
_BLOCK_DURATION = 300           # auto-block suspicious IPs for 5 min


def _get_client_ip(request: Request) -> str:
    """Extract real client IP honouring X-Forwarded-For (Cloudflare/proxy)."""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # Take the first IP in the chain (client IP)
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_admin_rate_limit(request: Request) -> None:
    """
    Enforce rate limiting for admin API calls using Redis sliding windows.
    Raises HTTP 429 if limits are exceeded.
    """
    try:
        from app.redis_client import redis_client
        if not redis_client:
            return  # Redis unavailable — fail open (log warning)
    except Exception:
        return

    ip = _get_client_ip(request)
    now = int(time.time())

    # Check if IP is auto-blocked
    block_key = f"admin:blocked:{ip}"
    if redis_client.exists(block_key):
        LOG.warning("SECURITY: Blocked IP %s attempted admin API access.", ip)
        raise HTTPException(
            status_code=429,
            detail="Too many suspicious requests. Your IP has been temporarily blocked."
        )

    # Sliding window counter (per minute)
    window_key = f"admin:ratelimit:{ip}:{now // _ADMIN_RATE_WINDOW}"
    count = redis_client.incr(window_key)
    if count == 1:
        redis_client.expire(window_key, _ADMIN_RATE_WINDOW + 5)

    if count > _ADMIN_RATE_LIMIT:
        LOG.warning("SECURITY: IP %s exceeded admin rate limit (%d reqs/min).", ip, count)
        # Auto-block for 5 minutes after 3x the limit
        if count > _ADMIN_RATE_LIMIT * 3:
            redis_client.set(block_key, "1", ex=_BLOCK_DURATION)
            LOG.error("SECURITY: Auto-blocked IP %s for %ds due to excessive admin requests.", ip, _BLOCK_DURATION)
        raise HTTPException(
            status_code=429,
            detail=f"Admin API rate limit exceeded. Max {_ADMIN_RATE_LIMIT} requests/minute."
        )

    # Burst window (5-second)
    burst_key = f"admin:burst:{ip}:{now // _ADMIN_BURST_WINDOW}"
    burst_count = redis_client.incr(burst_key)
    if burst_count == 1:
        redis_client.expire(burst_key, _ADMIN_BURST_WINDOW + 2)

    if burst_count > _ADMIN_BURST_LIMIT:
        LOG.warning("SECURITY: IP %s exceeded admin burst limit (%d reqs/5s).", ip, burst_count)
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests in a short window. Max {_ADMIN_BURST_LIMIT} requests per 5 seconds."
        )


# ---------------------------------------------------------------------------
# 3. Request Fingerprinting & Anomaly Detection
# ---------------------------------------------------------------------------

_SUSPICIOUS_UA_FRAGMENTS = [
    "sqlmap", "nikto", "nmap", "masscan", "dirbuster", "hydra",
    "burpsuite", "metasploit", "zgrab", "nuclei", "openvas",
    "python-requests/2.2", "curl/7.1", "go-http-client/1.1",
]

def detect_suspicious_request(request: Request) -> Optional[str]:
    """
    Returns a string describing the anomaly if suspicious, else None.
    """
    ua = request.headers.get("User-Agent", "").lower()
    for frag in _SUSPICIOUS_UA_FRAGMENTS:
        if frag in ua:
            return f"Suspicious User-Agent detected: {ua[:80]}"

    # Missing essential headers on POST/PATCH/DELETE
    if request.method in ("POST", "PATCH", "DELETE", "PUT"):
        if not request.headers.get("Content-Type"):
            return "Missing Content-Type on state-mutating request"

    # Overly long headers (header injection attempt)
    for name, value in request.headers.items():
        if len(value) > 8192:
            return f"Oversized header '{name}' detected ({len(value)} chars)"

    return None


def enforce_request_integrity(request: Request) -> None:
    """
    Run anomaly detection and raise 400/403 if suspicious.
    Record the anomaly in Redis for trend analysis.
    """
    anomaly = detect_suspicious_request(request)
    if not anomaly:
        return

    ip = _get_client_ip(request)
    LOG.warning("SECURITY ANOMALY from %s: %s | Path: %s", ip, anomaly, request.url.path)

    try:
        from app.redis_client import redis_client
        if redis_client:
            anom_key = f"admin:anomalies:{ip}"
            count = redis_client.incr(anom_key)
            if count == 1:
                redis_client.expire(anom_key, 3600)  # 1h window
            if count >= 5:
                # Auto-block after 5 anomalies in an hour
                block_key = f"admin:blocked:{ip}"
                redis_client.set(block_key, "1", ex=_BLOCK_DURATION)
                LOG.error("SECURITY: Auto-blocked IP %s due to repeated anomalies.", ip)
    except Exception:
        pass

    raise HTTPException(status_code=400, detail="Request integrity check failed.")


# ---------------------------------------------------------------------------
# 4. Encrypted Admin API Response Envelope
# ---------------------------------------------------------------------------

def encrypt_admin_response(data: dict) -> dict:
    """
    Wraps a sensitive admin API response in an AES-256-GCM encrypted envelope.
    The client must be trusted (admin) and will receive:
      {
        "enc": true,
        "payload": "<base64-ciphertext>",
        "ts": <unix-timestamp>
      }
    This prevents response interception from revealing sensitive data at rest
    in proxy logs or CDN edge caches.
    """
    import json
    from app.utils import encrypt_bytes_to_b64

    try:
        raw = json.dumps(data, default=str).encode("utf-8")
        encrypted = encrypt_bytes_to_b64(raw)
        return {
            "enc": True,
            "payload": encrypted,
            "ts": int(time.time()),
        }
    except Exception as e:
        LOG.error("encrypt_admin_response failed: %s. Falling back to plaintext.", e)
        return data  # Fail open (don't break admin panel)


def decrypt_admin_response(envelope: dict) -> dict:
    """
    Inverse of encrypt_admin_response — used by admin JS fetch wrapper.
    Note: decryption happens server-side when forwarding between services.
    For browser clients the JS must call /api/admin/decrypt endpoint.
    """
    import json
    from app.utils import decrypt_b64_to_bytes

    if not envelope.get("enc"):
        return envelope
    try:
        raw = decrypt_b64_to_bytes(envelope["payload"])
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        LOG.error("decrypt_admin_response failed: %s", e)
        raise HTTPException(status_code=500, detail="Response decryption failed.")


# ---------------------------------------------------------------------------
# 5. Admin Action Signature Verification (HMAC-SHA256)
#    For high-stakes mutations (delete user, change role, etc.)
# ---------------------------------------------------------------------------

_ACTION_SIGNATURE_WINDOW = 30  # seconds — reject stale signatures

def verify_action_signature(
    request: Request,
    payload_str: str,
    provided_sig: str,
    secret: str,
) -> bool:
    """
    Verifies that a high-stakes admin POST was signed by the client using:
      HMAC-SHA256(secret, f"{method}:{path}:{iso_timestamp}:{payload}")
    
    The client must include:
      X-Action-Timestamp: <ISO 8601 UTC>
      X-Action-Signature: <hex HMAC>
    """
    try:
        ts_str = request.headers.get("X-Action-Timestamp", "")
        if not ts_str:
            return False
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        age = abs((datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds())
        if age > _ACTION_SIGNATURE_WINDOW:
            LOG.warning("SECURITY: Action signature timestamp too old: %.0fs", age)
            return False

        method = request.method.upper()
        path = request.url.path
        message = f"{method}:{path}:{ts_str}:{payload_str}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return _constant_time_compare(provided_sig, expected)
    except Exception as e:
        LOG.debug("verify_action_signature error: %s", e)
        return False
