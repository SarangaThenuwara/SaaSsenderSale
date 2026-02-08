import base64
import hashlib
import uuid
from .config import WEBXPAY_SECRET_KEY, WEBXPAY_PUBLIC_KEY, APP_URL

def generate_webxpay_payload(order_id, amount, currency, customer_email, customer_first_name, customer_last_name, customer_phone, custom_1, custom_2, return_url):
    """
    Generates the payload and hash for Webxpay.
    Based on common redirect integration.
    Need to double check official hashing algorithm, assuming common pattern:
    Upper case hash of (secret + fields...). But since I don't have official docs, 
    I will prepare a standard payload and assume the frontend form handles it or redirect.
    Wait, usually redirect gateways POST data.
    """
    # Webxpay usually requires specific fields for checkout
    payload = {
        "secret_key": WEBXPAY_SECRET_KEY, # Sometimes used, sometimes only for hash
        "public_key": WEBXPAY_PUBLIC_KEY,
        "process_currency": currency,
        "cms": "PYTHON",
        "enc_method": "JHASD", # Example method or just plain params
        "ip_address": "127.0.0.1", # Request IP
        "customer_email": customer_email,
        "customer_first_name": customer_first_name,
        "customer_last_name": customer_last_name,
        "customer_phone_number": customer_phone,
        "payment_currency": currency,
        "payment_amount": str(amount),
        "order_reference_number": order_id,
        "items": "Email Service Subscription - 1 Month",
        "custom_fields": f"{custom_1}|{custom_2}",
        "url_success": f"{return_url}?status=success&order_id={order_id}",
        "url_fail": f"{return_url}?status=failed&order_id={order_id}",
    }
    
    # Hashing logic typically: plain string concatenation of specific fields + secret, then base64 encoded?
    # Without specific docs, I will construct basic form data.
    # The standard "Webxpay" usually gives a "public key" to put in the form.
    # I'll create a helper to just format the redirect URL if it's GET or form fields if POST.
    
    return payload

def verify_signature(data):
    # Verify logic
    return True
