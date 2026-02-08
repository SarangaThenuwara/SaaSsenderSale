import logging
import uuid
from datetime import datetime, timedelta
from bson.objectid import ObjectId

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .db import db
from .config import SECRET_KEY, APP_ENV, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_API_KEY, YOUTUBE_GUIDE_URL, COLAB_GENERATOR_URL
from .utils import generate_csrf_token, validate_csrf_token, encrypt_bytes_to_b64
from .storage_b2 import presign_upload, get_b2_status
import csv
import io
from .supabase_auth import signup as supabase_signup, signin as supabase_signin, get_user_from_token
from .send_worker import send_single_message_for_user
from .assigner import assign_pending_recipients
from .sync_pool import sync_from_main_database
from .webxpay import generate_webxpay_payload
from .config import WEBXPAY_DOMAIN, APP_URL
import socket
import requests
import json

# Configure logging to show INFO+ logs in console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
LOG = logging.getLogger(__name__)

# create app BEFORE any route decorators or middleware usage
app = FastAPI(title="SaaS Email Sender - Premium")

# --- Security: Rate Limiting ---
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
async def startup_event():
    LOG.info(">>> SAA SENDER APPLICATION STARTING <<<")
    LOG.info(">>> LOGGING CONFIGURED SUCCESSFULLY <<<")

# --- Middlewares ---
# (SessionMiddleware must be registered AFTER @app.middleware hooks 
# to ensure it executes BEFORE them in the request chain)


# --- Helpers: safe session access ---
def _get_session_dict(request: Request):
    """
    Return the session dict from the ASGI scope if present, otherwise None.
    Use request.scope directly to avoid the `assert "session" in self.scope` check
    that request.session performs when middleware is not installed.
    """
    return request.scope.get("session")

def current_session_user(request: Request):
    """
    Safely return the local user object for the current session, or None.
    This implementation checks the ASGI scope for 'session' to avoid
    raising an assertion when SessionMiddleware wasn't installed.
    """
    session = _get_session_dict(request)
    if not session:
        return None
    
    # 1) Check for hardcoded admin session
    if session.get("is_admin"):
        admin_user = db.users.find_one({"role": "admin"})
        if admin_user:
            admin_user["_id_str"] = str(admin_user["_id"])
            return admin_user
        # Fallback if no admin in DB yet? 
        # For now, if they are 'is_admin' in session, we can trust them
        # but the app expects a user object.
        return {"_id": "admin", "_id_str": "admin", "username": "admin", "role": "admin"}

    access_token = session.get("access_token")
    if not access_token:
        return None
    try:
        user_info = get_user_from_token(access_token)
    except Exception as e:
        LOG.debug("get_user_from_token failed: %s", e)
        return None
    if not user_info:
        return None
    # lookup or create local mapping
    local = db.users.find_one({"supabase_id": user_info["id"]})
    if not local:
        res = db.users.insert_one({
            "supabase_id": user_info["id"],
            "username": (user_info.get("email") or "").split("@")[0],
            "email": user_info.get("email"),
            "role": "user",
            "created_at": datetime.utcnow()
        })
        local = db.users.find_one({"_id": res.inserted_id})
    if local:
        local["_id_str"] = str(local["_id"])
    return local

def is_admin_request(request: Request):
    """
    Checks if a request is from an admin via:
    1. Session cookie (logged in browser)
    2. Static API Key (Header: X-Admin-API-Key)
    """
    # Check Session
    user = current_session_user(request)
    if user and user.get("role") == "admin":
        return True
    
    # Check API Key Header
    api_key = request.headers.get("X-Admin-API-Key")
    if api_key and api_key == ADMIN_API_KEY:
        return True
        
    return False


def get_csrf_session_id(request: Request):
    """
    Extremely stable identity for CSRF.
    Priority: session_id > "anonymous-placeholder".
    """
    try:
        session = request.session
        if session:
            if session.get("session_id"):
                return session.get("session_id")
            if session.get("access_token"):
                # Use a prefix/suffix to avoid potential overlap with session_ids
                return f"token:{session.get('access_token')[:32]}"
    except Exception:
        pass
    
    return "anon-stable"

# middleware to inject template context safely
@app.middleware("http")
async def add_template_context(request: Request, call_next):
    """
    Add session_user and csrf_token to request.state in a robust way.
    If SessionMiddleware is not present, we just set session_user=None
    and create a CSRF token using a fallback session identifier.
    """
    try:
        session = request.session
        request.state.session_user = None
        
        # 1) Ensure anonymous users have a stable ID for CSRF *BEFORE* generating the token
        if not session.get("session_id") and not session.get("access_token"):
            session["session_id"] = str(uuid.uuid4())
            LOG.info("Assigning new session_id: %s", session["session_id"])

        # 2) Now get the ID (it will definitely use the session_id we just set)
        csrf_sid = get_csrf_session_id(request)
        request.state.csrf_token = generate_csrf_token(csrf_sid)
        
        request.state.session_user = current_session_user(request)
        LOG.debug("Generated CSRF for SID %s: %s", csrf_sid, request.state.csrf_token)
    except Exception as e:
        LOG.exception("Error while preparing template context: %s", e)
        request.state.session_user = None
        request.state.csrf_token = ""
        
    response = await call_next(request)
    return response

def get_server_ips():
    """
    Detects private and public IP addresses.
    """
    private_ip = "N/A"
    public_ip = "N/A"
    
    try:
        # Private IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # doesn't even have to be reachable
        s.connect(('8.8.8.8', 1))
        private_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            private_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass

    try:
        # Public IP
        response = requests.get('https://api.ipify.org', timeout=3)
        if response.status_code == 200:
            public_ip = response.text
    except Exception:
        pass
        
    return {"private": private_ip, "public": public_ip}

# --- Security: Middleware ---

# 1. Security Headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Basic CSP - failing open but reporting (adjust as needed)
    # response.headers["Content-Security-Policy"] = "default-src 'self' https:; style-src 'self' 'unsafe-inline' https:; script-src 'self' 'unsafe-inline' https:;"
    return response

# 2. Trusted Host (Prevents Host Header attacks)
# Allow all for now, but restrict in production if domain is known
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Register SessionMiddleware LAST so it is the OUTERMOST layer
app.add_middleware(
    SessionMiddleware, 
    secret_key=SECRET_KEY, 
    https_only=(APP_ENV == "production"), 
    same_site="lax",
    session_cookie="saas_sender_session" # Unique name to avoid conflicts
)



def template_ctx(request: Request):
    return {
        "request": request,
        "session_user": getattr(request.state, "session_user", None),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "now": datetime.utcnow(),
        "youtube_guide_url": YOUTUBE_GUIDE_URL,
        "colab_generator_url": COLAB_GENERATOR_URL
    }

# --- Routes ---

@app.get("/privacy")
async def privacy(request: Request):
    ctx = template_ctx(request)
    try:
        return templates.TemplateResponse("premium/privacy.html", ctx)
    except Exception:
        # Fallback if specific template missing
        return templates.TemplateResponse("index.html", ctx)

@app.get("/terms")
async def terms(request: Request):
    ctx = template_ctx(request)
    try:
        return templates.TemplateResponse("premium/terms.html", ctx)
    except Exception:
        return templates.TemplateResponse("index.html", ctx)

@app.get("/robots.txt")
async def robots_txt():
    content = """User-agent: *
Disallow: /admin
Disallow: /user
Allow: /
"""
    return Response(content=content, media_type="text/plain")

@app.get("/robot.txt")
async def robot_txt():
    return await robots_txt()

@app.get("/sitemap.xml")
async def sitemap_xml(request: Request):
    base_url = str(request.base_url).rstrip("/")
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>{base_url}/</loc>
        <changefreq>daily</changefreq>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>{base_url}/login</loc>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>{base_url}/signup</loc>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>{base_url}/privacy</loc>
        <changefreq>monthly</changefreq>
        <priority>0.5</priority>
    </url>
    <url>
        <loc>{base_url}/terms</loc>
        <changefreq>monthly</changefreq>
        <priority>0.5</priority>
    </url>
</urlset>
"""
    return Response(content=xml_content, media_type="application/xml")

@app.get("/sitemap")
async def sitemap(request: Request):
    return await sitemap_xml(request)

@app.get("/health")
@app.get("/api/health")
async def health_check():
    return JSONResponse({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

@app.get("/api")
async def api_info():
    return JSONResponse({"message": "SaaS Email Sender API", "version": "1.0.0"})

@app.get("/api/user/{user_id}/dashboard")
async def api_dashboard_alias(user_id: str, request: Request):
    # This acts as an alias or redirect to the HTML dashboard
    # If the user specifically wanted JSON data here, we'd need a separate logic
    # but based on the 404 logs, we'll redirect to the existing dashboard route.
    return RedirectResponse(url=f"/user/{user_id}/dashboard")


@app.get("/")
def index(request: Request):
    ctx = template_ctx(request)
    ctx.update({"now": datetime.utcnow()})
    # Use premium landing template if present, otherwise fallback to basic index.html
    try:
        return templates.TemplateResponse("premium/index.html", ctx)
    except Exception:
        return templates.TemplateResponse("index.html", ctx)

@app.get("/admin-login")
def admin_login_form(request: Request):
    return templates.TemplateResponse("premium/admin_login.html", template_ctx(request))

@app.post("/admin-login")
@limiter.limit("5/minute")
async def admin_login_submit(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(None)):
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
        return templates.TemplateResponse("premium/admin_login.html", {**template_ctx(request), "error": "CSRF failed"})
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session.clear()
        request.session["is_admin"] = True
        return RedirectResponse(url="/admin", status_code=303)
    
    return templates.TemplateResponse("premium/admin_login.html", {**template_ctx(request), "error": "Invalid credentials"})

@app.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse("premium/login.html", template_ctx(request))

@app.post("/login")
@limiter.limit("10/minute")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...), csrf: str = Form(None)):
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
        ua = request.headers.get("user-agent", "unknown")
        LOG.warning("CSRF validation failed. SID: %s | UA: %s", sid, ua)
        return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": "CSRF validation failed. Please refresh and try again."})
    try:
        token_resp = supabase_signin(email=email, password=password)
    except Exception as e:
        # Handle 400 (Bad Request) from Supabase (wrong password etc) without full traceback
        import requests
        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code == 400:
            LOG.warning("Auth failure for %s: %s", email, e.response.text)
        else:
            LOG.exception("Supabase signin error")
        return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": "Login failed"})
    access_token = token_resp.get("access_token")
    refresh_token = token_resp.get("refresh_token")
    if not access_token:
        return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": "Login failed: no token"})
    # store tokens in session (refresh token encrypted when present)
    if _get_session_dict(request) is None:
        # ensure session exists by touching request.session (this will raise if SessionMiddleware missing)
        request.session  # keep for clarity; SessionMiddleware should be present
    request.session.clear()
    request.session["access_token"] = access_token
    if refresh_token:
        request.session["refresh_token_enc"] = encrypt_bytes_to_b64(refresh_token.encode())
    # map to local user
    user_info = get_user_from_token(access_token)
    local = db.users.find_one({"supabase_id": user_info["id"]})
    if not local:
        res = db.users.insert_one({
            "supabase_id": user_info["id"],
            "username": (user_info.get("email") or "").split("@")[0],
            "email": user_info.get("email"),
            "role": "user",
            "created_at": datetime.utcnow()
        })
        local = db.users.find_one({"_id": res.inserted_id})
    return RedirectResponse(url=f"/user/{local['_id']}/dashboard", status_code=302)


@app.get("/forgot-password")
def forgot_password_form(request: Request):
    return templates.TemplateResponse("premium/forgot-password.html", template_ctx(request))

@app.post("/forgot-password")
def forgot_password_submit(request: Request, email: str = Form(...), csrf: str = Form(None)):
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
        return templates.TemplateResponse("premium/forgot-password.html", {**template_ctx(request), "error": "CSRF validation failed"})
    
    # TODO: Implement actual password reset logic
    # For now, just redirect to login
    # In production, you would:
    # 1. Check if email exists in database
    # 2. Generate a password reset token
    # 3. Send email with reset link
    # 4. Store token with expiration in database
    
    LOG.info(f"Password reset requested for: {email}")
    # Redirect to login page after successful submission
    return RedirectResponse(url="/login", status_code=302)

@app.get("/signup")
def signup_form(request: Request):
    return templates.TemplateResponse("premium/signup.html", template_ctx(request))

@app.post("/signup")
@limiter.limit("5/minute")
def signup_submit(request: Request, email: str = Form(...), password: str = Form(...), csrf: str = Form(None)):
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
        ua = request.headers.get("user-agent", "unknown")
        LOG.warning("CSRF validation failed. SID: %s | UA: %s", sid, ua)
        return templates.TemplateResponse("premium/signup.html", {**template_ctx(request), "error": "CSRF validation failed. Please refresh and try again."})
    try:
        signup_resp = supabase_signup(email=email, password=password)
        # Check if we got a token immediately (auto-confirm enabled?)
        access_token = signup_resp.get("access_token")
        refresh_token = signup_resp.get("refresh_token")
        
        if not access_token:
            # Maybe try signin? If email conf is required, this will fail.
            # We should assume if no token from signup, we need confirmation.
            # But just in case, we can TRY signin, and if it fails with 'Email not confirmed', we handle it.
            try:
                token_resp = supabase_signin(email=email, password=password)
                access_token = token_resp.get("access_token")
                refresh_token = token_resp.get("refresh_token")
            except Exception:
                # Signin failed, likely waiting for confirmation
                return templates.TemplateResponse("premium/signup.html", {**template_ctx(request), "error": "Signup successful! Please check your email to confirm your account."})

    except Exception as e:
        # Handle 400 (Bad Request) from Supabase with specific error messages
        import requests
        error_msg = "Sign up failed"
        
        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
            if e.response.status_code == 400:
                try:
                    error_data = e.response.json()
                    error_detail = error_data.get("msg", "") or error_data.get("error_description", "")
                    
                    # Parse common Supabase errors
                    if "already registered" in error_detail.lower() or "already exists" in error_detail.lower():
                        error_msg = "This email is already registered. Please sign in instead."
                    elif "password" in error_detail.lower() and ("weak" in error_detail.lower() or "short" in error_detail.lower()):
                        error_msg = "Password is too weak. Please use at least 8 characters."
                    elif "invalid" in error_detail.lower() and "email" in error_detail.lower():
                        error_msg = "Invalid email format. Please check your email address."
                    else:
                        error_msg = f"Sign up failed: {error_detail}"
                    
                    LOG.warning("Signup failed for %s: %s", email, error_detail)
                except Exception:
                    error_msg = "Sign up failed. Please check your email and password."
            else:
                LOG.exception("Supabase signup/signin failed")
                error_msg = "Sign up failed. Please try again later."
        else:
            LOG.exception("Supabase signup/signin failed")
            error_msg = "Sign up failed. Please try again later."
        
        return templates.TemplateResponse("premium/signup.html", {**template_ctx(request), "error": error_msg})

    if not access_token:
        # Should be covered above, but safe fallback
        return templates.TemplateResponse("premium/signup.html", {**template_ctx(request), "error": "Signup created — confirm your email."})
    if _get_session_dict(request) is None:
        request.session
    request.session.clear()
    request.session["access_token"] = access_token
    if refresh_token:
        request.session["refresh_token_enc"] = encrypt_bytes_to_b64(refresh_token.encode())
    user_info = get_user_from_token(access_token)
    local = db.users.find_one({"supabase_id": user_info["id"]})
    if not local:
        res = db.users.insert_one({
            "supabase_id": user_info["id"],
            "username": (user_info.get("email") or "").split("@")[0],
            "email": user_info.get("email"),
            "role": "user",
            "daily_limit": 240,
            "created_at": datetime.utcnow()
        })
        local = db.users.find_one({"_id": res.inserted_id})
    return RedirectResponse(url=f"/user/{local['_id']}/dashboard", status_code=302)

@app.get("/logout")
def logout(request: Request):
    # clear server session
    session = _get_session_dict(request)
    if session is not None:
        request.session.clear()
    return RedirectResponse(url="/", status_code=302)

# Presign endpoints
@app.post("/api/presign_upload")
async def api_presign_upload(request: Request):
    form = await request.form()
    filename = form.get("filename")
    content_type = form.get("content_type") or "application/pdf"
    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]
    if content_type not in allowed_types:
        return JSONResponse({"error": "Invalid content type. Only PDF and Word documents are allowed."}, status_code=400)

    try:
        res = presign_upload(filename=filename, content_type=content_type)
    except Exception as e:
        LOG.exception("presign failed")
        return JSONResponse({"error": "presign failed"}, status_code=500)
    return JSONResponse(res)

@app.post("/api/presign_complete")
async def api_presign_complete(request: Request):
    body = await request.json()
    key = body.get("key")
    filename = body.get("filename")
    if not key:
        return JSONResponse({"error": "key required"}, status_code=400)
    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    db.users.update_one({"_id": user["_id"]}, {"$set": {"cv_b2_key": key, "cv_filename": filename, "cv_uploaded_at": datetime.utcnow()}})
    return JSONResponse({"ok": True, "key": key})

@app.post("/api/test_send")
@limiter.limit("5/minute")
async def api_test_send(request: Request):

    payload = await request.json()
    to_email = payload.get("to_email")
    if not to_email:
        return JSONResponse({"error": "to_email required"}, status_code=400)
    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    try:
        res = send_single_message_for_user(user_id=user["_id"], to_email=to_email, subject_override=payload.get("subject"), body_override=payload.get("body"))
        return JSONResponse({"ok": True, "result": res})
    except Exception as e:
        LOG.exception("test send failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.get("/user/{user_id}/dashboard")
def user_dashboard(request: Request, user_id: str):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    if str(user["_id"]) != user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        me = db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid user ID")
        
    if not me:
         raise HTTPException(status_code=404, detail="User not found")
    
    # Ensure 'me' also has _id_str for the template
    me["_id_str"] = str(me["_id"])
    
    assigned = db.recipients.count_documents({"assigned_to": me["_id"], "status": {"$in": ["Assigned", "InProgress"]}})
    pending = db.recipients.count_documents({"status": "Pending"})
    ctx = {**template_ctx(request), "user": me, "assigned": assigned, "pending": pending}
    try:
        return templates.TemplateResponse("premium/dashboard.html", ctx)
    except Exception:
        return templates.TemplateResponse("onboard.html", ctx)

@app.get("/api/user/report")
async def api_user_report(request: Request):
    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    
    # Fetch last 50 processed recipients
    recipients = list(db.recipients.find(
        {"assigned_to": user["_id"], "status": {"$in": ["Sent", "Failed"]}}
    ).sort("sent_at", -1).limit(50))
    
    for r in recipients:
        r["_id"] = str(r["_id"])
        r["assigned_to"] = str(r["assigned_to"])
        if "sent_at" in r:
            r["sent_at"] = r["sent_at"].isoformat()
            
    return JSONResponse(recipients)


@app.get("/settings")
def settings_get(request: Request):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("premium/settings.html", {**template_ctx(request), "user": user})

@app.post("/settings")
async def settings_post(
    request: Request,
    sender_email: str = Form(None),
    credentials_base64: str = Form(None),
    token_base64: str = Form(None),
    subject_template: str = Form(None),
    body_template: str = Form(None),
    csrf: str = Form(None)
):

    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
        return templates.TemplateResponse("premium/settings.html", {**template_ctx(request), "error": "CSRF validation failed", "user": current_session_user(request)})
    
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")

    # --- Validation ---
    errors = []
    import re
    import base64
    import json
    import bleach  # For sanitization

    # 1) Sender Email
    if sender_email and not re.match(r"[^@]+@[^@]+\.[^@]+", sender_email):
        errors.append("Invalid Sender Email format.")

    # 2) Credentials
    if credentials_base64:
        # Strictly enforce Base64 (remove all whitespace/newlines)
        clean_cred = "".join(credentials_base64.split())
        # Fix padding if missing
        missing_padding = len(clean_cred) % 4
        if missing_padding:
            clean_cred += '=' * (4 - missing_padding)
            
        try:
            # Try standard base64 first
            try:
                base64.b64decode(clean_cred)
            except Exception:
                # Fallback to urlsafe base64
                base64.urlsafe_b64decode(clean_cred)
            
            credentials_base64 = clean_cred
        except Exception as e:
            LOG.error("Admin credentials validation failed: %s", e)
            errors.append("Credentials: Not a valid Base64 string. Please copy the full string.")



    # 3) Token
    if token_base64:
        # Strictly enforce Base64 (remove all whitespace/newlines)
        clean_tok = "".join(token_base64.split())
        # Fix padding if missing
        missing_padding = len(clean_tok) % 4
        if missing_padding:
            clean_tok += '=' * (4 - missing_padding)
            
        try:
            try:
                base64.b64decode(clean_tok)
            except Exception:
                base64.urlsafe_b64decode(clean_tok)
                
            token_base64 = clean_tok
        except Exception as e:
             LOG.error("Admin token validation failed: %s", e)
             errors.append("Token: Not a valid Base64 string. Ensure you are copying correctly.")





    # 4) Templates
    if not subject_template or "{first_name}" not in subject_template:

        errors.append("Subject template must contain {first_name} for personalization.")
    else:
        # Sanitize subject
        subject_template = bleach.clean(subject_template, tags=[], strip=True)

    if not body_template or "{first_name}" not in body_template.lower():
        errors.append("Body template MUST contain {first_name} (case-insensitive) for personalization.")

    else:
        # Sanitize body (allow some basic formatting if needed, or strip all)
        # For email templates, we might want to allow basic HTML.
        allowed_tags = ['b', 'i', 'u', 'strong', 'em', 'p', 'br', 'a', 'div', 'span', 'ul', 'li', 'ol']
        allowed_attrs = {'a': ['href', 'title', 'target']}
        body_template = bleach.clean(body_template, tags=allowed_tags, attributes=allowed_attrs, strip=True)

    if errors:
        # Return to settings with current user but merge form data so they don't lose input
        merged_user = {**user, "sender_email": sender_email, "credentials_base64": credentials_base64, 
                       "token_base64": token_base64, "subject_template": subject_template, "body_template": body_template}
        return templates.TemplateResponse("premium/settings.html", {
            **template_ctx(request), 
            "error": " | ".join(errors), 
            "user": merged_user
        })

    # Encryption of sensitive data before storage
    encrypted_credentials = None
    if credentials_base64:
        # It's already base64 (either from user or we encoded it above)
        # We want to encrypt this STRING.
        try:
             encrypted_credentials = encrypt_bytes_to_b64(credentials_base64.encode())
        except Exception:
             LOG.exception("Failed to encrypt credentials")
             # Fallback? Probably better to fail request
             encrypted_credentials = credentials_base64 # insecure fallback, or error?
    
    encrypted_token = None
    if token_base64:
         try:
             encrypted_token = encrypt_bytes_to_b64(token_base64.encode())
         except Exception:
             LOG.exception("Failed to encrypt token")
             encrypted_token = token_base64

    update_data = {
        "sender_email": sender_email,
        "subject_template": subject_template,
        "body_template": body_template,
        "updated_at": datetime.utcnow()
    }
    
    if encrypted_credentials:
        update_data["credentials_base64"] = encrypted_credentials
    if encrypted_token:
        update_data["token_base64"] = encrypted_token
    
    db.users.update_one({"_id": user["_id"]}, {"$set": update_data})

    
    # Refresh user for response
    user = db.users.find_one({"_id": user["_id"]})
    return templates.TemplateResponse("premium/settings.html", {**template_ctx(request), "user": user, "success": "Settings updated successfully!"})

@app.post("/api/validate_credentials")
@limiter.limit("5/minute")
async def api_validate_credentials(request: Request):

    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    
    try:
        from .gmail_helpers import get_gmail_service_for_user
        service = get_gmail_service_for_user(user["_id"])
        # Simple call to verify credentials
        service.users().getProfile(userId="me").execute()
        
        db.users.update_one(
            {"_id": user["_id"]}, 
            {"$set": {"credentials_valid": True, "last_validated": datetime.utcnow()}}
        )
        return JSONResponse({"ok": True, "message": "Credentials validated successfully!"})
    except Exception as e:
        LOG.exception("Credential validation failed")
        db.users.update_one(
            {"_id": user["_id"]}, 
            {"$set": {"credentials_valid": False, "last_validated": datetime.utcnow()}}
        )
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

@app.post("/api/campaign/toggle")
@limiter.limit("10/minute")
async def api_campaign_toggle(request: Request):

    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    
    body = await request.json()
    active = body.get("active", False)
    
    # If starting, ensure credentials are valid AND payment logic if enabled
    if active:
        # 1. Credentials Check
        if not user.get("credentials_valid"):
             return JSONResponse({"error": "Please validate your credentials in Settings before starting."}, status_code=400)
        
        # 2. Payment Check
        settings = db.settings.find_one({"_id": "global"}) or {}
        if settings.get("payment_gateway_enabled", False):
             if user.get("role") != "admin":
                 expires_at = user.get("subscription_expires_at")
                 is_paid = user.get("is_paid")
                 if not is_paid or not expires_at or expires_at < datetime.utcnow():
                     return JSONResponse({"error": "Subscription required", "payment_required": True}, status_code=402)
    
    db.users.update_one({"_id": user["_id"]}, {"$set": {"campaign_active": active}})
    return JSONResponse({"ok": True, "active": active})

@app.get("/admin")
def admin_dashboard(request: Request):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    users = list(db.users.find({}))
    for u in users:
        u["_id_str"] = str(u["_id"])
        u["assigned_count"] = db.recipients.count_documents({"assigned_to": u["_id"]})
        u["pending_capacity"] = max(0, u.get("daily_limit", 240) - u.get("daily_sent", 0))

    pending_pool = db.recipients.count_documents({"status": "Pending"})
    active_users = [u for u in users if u.get("campaign_active") and u.get("credentials_valid")]
    total_capacity = sum(u.get("daily_limit", 240) for u in active_users)

    # Infrastructure Status
    b2_status = get_b2_status()
    server_ips = get_server_ips()
    
    # Check global settings
    settings = db.settings.find_one({"_id": "global"}) or {}
    payment_active = settings.get("payment_gateway_enabled", False)
    
    mongo_status = {"ok": False}

    try:
        db.command("ping")
        stats = db.command("dbstats")
        
        # Try serverStatus for more details (might fail on some Atlas tiers, so handle gracefully)
        try:
            srv_status = db.command("serverStatus")
            conns = srv_status.get("connections", {})
        except Exception:
            srv_status = {}
            conns = {}

        mongo_status = {
            "ok": True, 
            "collections": stats.get("collections", 0),
            "objects": stats.get("objects", 0),
            "data_size": round(stats.get("dataSize", 0) / (1024*1024), 2),  # MB
            "index_size": round(stats.get("indexSize", 0) / (1024*1024), 2),  # MB
            "avg_obj_size": round(stats.get("avgObjSize", 0), 2), # Bytes
            "active_conns": conns.get("current", "N/A"),
            "available_conns": conns.get("available", "N/A"),
            "version": srv_status.get("version", "N/A")
        }
    except Exception as e:
        mongo_status["error"] = str(e)

    ctx = {
        **template_ctx(request),
        "users": users,
        "pending_pool": pending_pool,
        "active_users_count": len(active_users),
        "total_capacity": total_capacity,
        "b2_status": b2_status,
        "mongo_status": mongo_status,
        "server_ips": server_ips,
        "payment_active": payment_active
    }
    return templates.TemplateResponse("premium/admin.html", ctx)


@app.post("/admin/sync_pool")
async def admin_sync_pool(request: Request, csrf: str = Form(None)):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    if user.get("role") != "admin":
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
         return JSONResponse({"error": "CSRF failed"}, status_code=400)

    try:
        res = sync_from_main_database()
        LOG.info("Sync job run: %s", res)
    except Exception as e:
        LOG.exception("Sync job failed")
        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)

    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/assign")
async def admin_assign(request: Request, csrf: str = Form(None)):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    if user.get("role") != "admin":
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
         return JSONResponse({"error": "CSRF failed"}, status_code=400)

    try:
        res = assign_pending_recipients()
        LOG.info("Assignment job run: %s", res)
    except Exception as e:
        LOG.exception("Assignment job failed")
        return JSONResponse({"error": f"Assignment failed: {str(e)}"}, status_code=500)

    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/payments/toggle")
async def admin_payments_toggle(request: Request, active: str = Form("false"), csrf: str = Form(None)):
    user = current_session_user(request)
    if not user or user.get("role") != "admin":
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
          return JSONResponse({"error": "CSRF failed"}, status_code=400)
    
    is_active = (active.lower() == "true")
    # Upsert global setting
    db.settings.update_one({"_id": "global"}, {"$set": {"payment_gateway_enabled": is_active}}, upsert=True)
    
    return RedirectResponse(url="/admin", status_code=303)

# --- Payment Routes ---

@app.get("/payment")
def payment_page(request: Request):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    # Check if payment is enabled globally
    settings = db.settings.find_one({"_id": "global"}) or {}
    if not settings.get("payment_gateway_enabled", False) and user.get("role") != "admin":
        # If disabled (and not admin testing), redirect to dashboard?
        # Or maybe just show onboard.
        return RedirectResponse(url=f"/user/{user['_id']}/dashboard")

    # Generate Order ID and Payload for the form
    order_id = f"SUB-{uuid.uuid4().hex[:8].upper()}"
    amount = 5.00
    currency = "USD" # Webxpay currency
    
    payload = generate_webxpay_payload(
        order_id=order_id,
        amount=amount,
        currency=currency,
        customer_email=user.get("email"),
        customer_first_name=user.get("username").split()[0], # simplistic
        customer_last_name="",
        customer_phone="0000000000", # Placeholder if not collected
        custom_1=str(user["_id"]),
        custom_2="subscription",
        return_url=f"{APP_URL}/payment/callback"
    )
    
    # Store order attempt?
    db.payments.insert_one({
        "order_id": order_id,
        "user_id": user["_id"],
        "amount": amount,
        "currency": currency,
        "status": "Initiated",
        "created_at": datetime.utcnow()
    })
    
    return templates.TemplateResponse("premium/payment.html", {
        **template_ctx(request),
        "user": user,
        "payload": payload,
        "webxpay_url": WEBXPAY_DOMAIN
    })

@app.api_route("/payment/callback", methods=["GET", "POST"])
async def payment_callback(request: Request):
    # Webxpay might send data via GET or POST depending on integration
    # We accept both for safety.
    params = {}
    if request.method == "POST":
         try:
            form = await request.form()
            params = dict(form)
         except Exception:
             pass
    else:
        params = dict(request.query_params)
        
    status = params.get("status")
    order_id = params.get("order_id") or params.get("order_reference_number")
    
    # Basic verification (In prod, verify hash signature!)
    if status == "success" and order_id:
        # Find payment
        payment = db.payments.find_one({"order_id": order_id})
        if payment:
            if payment["status"] != "Completed":
                db.payments.update_one({"_id": payment["_id"]}, {"$set": {"status": "Completed", "completed_at": datetime.utcnow(), "raw_response": str(params)}})
                
                # Activate subscription for 30 days
                user_id = payment["user_id"]
                expiry = datetime.utcnow() + datetime.timedelta(days=30)
                
                db.users.update_one({"_id": user_id}, {"$set": {
                    "is_paid": True,
                    "subscription_expires_at": expiry
                }})
                LOG.info("Subscription activated for user %s until %s", user_id, expiry)
        
        # Redirect to Dashboard with success message
        # We need to find the user from payment if not in session?
        # Usually user is in session if browser redirect.
        user = current_session_user(request)
        if user:
             return RedirectResponse(url=f"/user/{user['_id']}/dashboard?paid=true", status_code=303)
        return RedirectResponse(url="/login", status_code=303)
        
    else:
        LOG.warning("Payment failed or invalid: %s", params)
        return RedirectResponse(url="/payment?error=failed", status_code=303)



# --- Admin API ---
@app.get("/api/admin/users")
def api_admin_list_users(request: Request):
    if not is_admin_request(request):
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    users = list(db.users.find({}, {"credentials_base64": 0, "token_base64": 0}))
    for u in users:
        u["_id"] = str(u["_id"])
    return JSONResponse(users)

@app.post("/api/admin/users")
async def api_admin_create_user(request: Request):
    if not is_admin_request(request):
         return JSONResponse({"error": "Admin access required"}, status_code=403)

    
    body = await request.json()
    email = body.get("email")
    password = body.get("password")
    
    if not email or not password:
         return JSONResponse({"error": "Email and password required"}, status_code=400)

    # Use Supabase to create the user auth record
    try:
        resp = supabase_signup(email=email, password=password)
        # We don't auto-confirm here usually, but if we get a user ID back:
        supabase_id = resp.get("id") or resp.get("user", {}).get("id")
        
        if not supabase_id:
             # Try signin to see if they exist?
             # For now, just rely on error or success
             pass
             
        # Create local user record if successful
        if supabase_id:
            local = db.users.find_one({"supabase_id": supabase_id})
            if not local:
                res = db.users.insert_one({
                    "supabase_id": supabase_id,
                    "username": email.split("@")[0],
                    "email": email,
                    "role": "user",
                    "daily_limit": 240,
                    "created_at": datetime.utcnow()
                })
                return JSONResponse({"ok": True, "id": str(res.inserted_id)})
            return JSONResponse({"ok": True, "id": str(local["_id"]), "message": "User already existed locally"})
            
    except Exception as e:
        LOG.exception("Failed to create user via Admin API")
        return JSONResponse({"error": str(e)}, status_code=500)
    
    return JSONResponse({"error": "Could not create user"}, status_code=400)

@app.patch("/api/admin/users/{user_id}")
async def api_admin_update_user(user_id: str, request: Request):
    if not is_admin_request(request):
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    body = await request.json()
    # Fields that admin is allowed to update via API
    allowed_updates = ["daily_limit", "role", "is_paid", "username", "campaign_active", "subscription_expires_at"]
    updates = {k: v for k, v in body.items() if k in allowed_updates}
    
    if not updates:
        return JSONResponse({"error": "No valid update fields provided"}, status_code=400)
    
    # Data type conversion/normalization
    if "daily_limit" in updates:
        try:
            updates["daily_limit"] = int(updates["daily_limit"])
        except ValueError:
            return JSONResponse({"error": "daily_limit must be an integer"}, status_code=400)
            
    if "is_paid" in updates:
        updates["is_paid"] = bool(updates["is_paid"])
        # If setting to true and no expiry provided, default to +30 days
        if updates["is_paid"] and "subscription_expires_at" not in updates:
             updates["subscription_expires_at"] = datetime.utcnow() + timedelta(days=30)
    
    if "subscription_expires_at" in updates and isinstance(updates["subscription_expires_at"], str):
        try:
            updates["subscription_expires_at"] = datetime.fromisoformat(updates["subscription_expires_at"].replace("Z", "+00:00"))
        except ValueError:
            return JSONResponse({"error": "Invalid date format for subscription_expires_at. Use ISO format."}, status_code=400)

    try:
        res = db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
        if res.matched_count == 0:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return JSONResponse({"ok": True, "updated_fields": list(updates.keys())})
    except Exception as e:
        LOG.error("Admin update user failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/admin/users/{user_id}")
async def api_admin_delete_user(user_id: str, request: Request):
    if not is_admin_request(request):
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    try:
        # Note: This only deletes from local MongoDB. 
        # To delete from Supabase, a Service Role Key would be required.
        res = db.users.delete_one({"_id": ObjectId(user_id)})
        if res.deleted_count == 0:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return JSONResponse({"ok": True, "message": "User deleted from local database"})
    except Exception as e:
        LOG.error("Admin delete user failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/admin/stats")
def api_admin_stats(request: Request):
    if not is_admin_request(request):
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    total_users = db.users.count_documents({})
    active_campaigns = db.users.count_documents({"campaign_active": True})
    paid_users = db.users.count_documents({"is_paid": True})
    total_recipients = db.recipients.count_documents({})
    pending_recipients = db.recipients.count_documents({"status": "Pending"})
    
    return JSONResponse({
        "total_users": total_users,
        "active_campaigns": active_campaigns,
        "paid_users": paid_users,
        "recipients": {
            "total": total_recipients,
            "pending": pending_recipients
        },
        "system": {
            "environment": APP_ENV,
            "now": datetime.utcnow().isoformat()
        }
    })