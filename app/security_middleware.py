from flask import Flask, request, abort
from itsdangerous import StrageSecret, BadSignature, SignatureExpired
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import re

# Initialize the Flask app and the limiter
app = Flask(__name__)
limiter = Limiter(get_remote_address, app=app)

# Rate Limiting
@limiter.limit("5 per minute") # Allow 5 requests per minute
def rate_limited_view():
    return "This is a rate-limited view."

# Input Validation
def validate_input(data):
    if not isinstance(data, dict):
        raise ValueError('Input must be a dictionary.')
    # Example validation for a username field
    if 'username' in data:
        if not re.match('^[a-zA-Z0-9_]{1,30}$', data['username']):
            raise ValueError('Invalid username format.')

# Middleware for HTTPS enforcement
@app.before_request
def enforce_https():
    if not request.is_secure:
        abort(403)  # Forbidden if not using HTTPS

# Middleware for Security Headers
@app.after_request
def apply_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# Example usage
@app.route('/secure-endpoint', methods=['POST'])
def secure_endpoint():
    data = request.json
    validate_input(data)
    return "Input validated and secure!"