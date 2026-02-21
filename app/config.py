import os
from dotenv import load_dotenv
import sys

load_dotenv()

# Environment
APP_ENV = os.getenv("APP_ENV", "development")  # "development" or "production"

# Secrets
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")  # change in production
FERNET_KEY = os.getenv("FERNET_KEY")  # optional, required if you want token encryption
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "admin-secret-key")

# SECURITY: Key Enforcement
if not FERNET_KEY:
    print("🚨 CRITICAL ERROR: FERNET_KEY is missing!")
    print("💡 Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
    sys.exit(1)

# SECURITY: Enforce strong secrets in production
if APP_ENV == "production":
    weak_secrets = []
    
    if SECRET_KEY == "change-me" or len(SECRET_KEY) < 32:
        weak_secrets.append("SECRET_KEY must be at least 32 characters")
    
    if len(FERNET_KEY) < 32:
        weak_secrets.append("FERNET_KEY must be a valid 32-byte Fernet key (use the generator above)")
    
    if ADMIN_PASSWORD == "admin" or len(ADMIN_PASSWORD) < 12:
        weak_secrets.append("ADMIN_PASSWORD must be at least 12 characters and not 'admin'")
    
    if ADMIN_API_KEY == "admin-secret-key" or len(ADMIN_API_KEY) < 32:
        weak_secrets.append("ADMIN_API_KEY must be at least 32 characters and not default")
    
    if weak_secrets:
        print("🚨 SECURITY ERROR: Weak secrets detected in production mode!")
        for error in weak_secrets:
            print(f"   ❌ {error}")
        print("\n💡 Generate strong secrets with: python -c 'import secrets; print(secrets.token_urlsafe(32))'")
        sys.exit(1)

# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "saa_sender")

# Redis / Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# Backblaze B2 (S3-compatible)
B2_KEY_ID = os.getenv("B2_S3_KEY_ID")
B2_APP_KEY = os.getenv("B2_S3_APP_KEY")
B2_BUCKET = os.getenv("B2_S3_BUCKET")
B2_ENDPOINT = os.getenv("B2_S3_ENDPOINT")

# Supabase (server-side calls)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Gmail scopes
GMAIL_SCOPES = os.getenv("GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.send").split(",")

# Guides
YOUTUBE_GUIDE_URL = os.getenv("YOUTUBE_GUIDE_URL", "#")
COLAB_GENERATOR_URL = os.getenv("COLAB_GENERATOR_URL", "#")

# Webxpay
WEBXPAY_SECRET_KEY = os.getenv("WEBXPAY_SECRET_KEY", "your-webxpay-secret")
WEBXPAY_PUBLIC_KEY = os.getenv("WEBXPAY_PUBLIC_KEY", "your-webxpay-public")
WEBXPAY_DOMAIN = os.getenv("WEBXPAY_DOMAIN", "https://cms.webxpay.com/payments/checkout")  # Sandbox/Production URL
APP_URL = os.getenv("APP_URL", "http://localhost:8000")

# Session Security
SESSION_IDLE_TIMEOUT = 30 * 60  # 30 minutes in seconds
SESSION_ABSOLUTE_TIMEOUT = 24 * 60 * 60  # 24 hours in seconds