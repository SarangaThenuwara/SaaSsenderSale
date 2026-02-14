import base64
import hashlib
import uuid
import hmac
from urllib.parse import urlencode, quote_plus
from .config import WEBXPAY_SECRET_KEY, WEBXPAY_PUBLIC_KEY, APP_URL

def sign_params(params):
    """
    Sign a dictionary of parameters using HMAC-SHA256.
    Returns the signature string.
    """
    # Sort keys to ensure deterministic output
    sorted_keys = sorted(params.keys())
    # Create string to sign: key=value&key2=value2...
    query_parts = []
    for k in sorted_keys:
        val = str(params[k])
        query_parts.append(f"{k}={val}")
        
    query_string = "&".join(query_parts)
    
    signature = hmac.new(
        WEBXPAY_SECRET_KEY.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature

def verify_payment_return(order_id, status, signatures):
    """
    Verify the signature for order_id and status.
    signatures: The signature string received.
    """
    params = {"order_id": order_id, "status": status}
    expected_sig = sign_params(params)
    return hmac.compare_digest(signatures, expected_sig)

def generate_webxpay_payload(order_id, amount, currency, customer_email, customer_first_name, customer_last_name, customer_phone, custom_1, custom_2, return_url):
    """
    Generates the payload for Webxpay.
    """
    
    # Generate signatures for success/fail URLs
    # We explicitly sign ONLY status and order_id so verification is robust against extra params
    success_params = {"status": "success", "order_id": order_id}
    success_sig = sign_params(success_params)
    url_success = f"{return_url}?{urlencode(success_params)}&signature={success_sig}"
    
    fail_params = {"status": "failed", "order_id": order_id}
    fail_sig = sign_params(fail_params)
    url_fail = f"{return_url}?{urlencode(fail_params)}&signature={fail_sig}"

    # SECURITY: Never send secret_key to external services - only use for server-side signing
    payload = {
        "public_key": WEBXPAY_PUBLIC_KEY,
        "process_currency": currency,
        "cms": "PYTHON",
        "enc_method": "JHASD", 
        "ip_address": "127.0.0.1", 
        "customer_email": customer_email,
        "customer_first_name": customer_first_name,
        "customer_last_name": customer_last_name,
        "customer_phone_number": customer_phone,
        "payment_currency": currency,
        "payment_amount": str(amount),
        "order_reference_number": order_id,
        "items": "Email Service Subscription - 1 Month",
        "custom_fields": f"{custom_1}|{custom_2}",
        "url_success": url_success,
        "url_fail": url_fail,
    }
    
    return payload
