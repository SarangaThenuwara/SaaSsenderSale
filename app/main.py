import logging
import uuid
import secrets
from datetime import datetime, timedelta
from bson.objectid import ObjectId

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .db import db
from .config import (
    SECRET_KEY, APP_ENV, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_API_KEY, 
    YOUTUBE_GUIDE_URL, COLAB_GENERATOR_URL, SESSION_IDLE_TIMEOUT, SESSION_ABSOLUTE_TIMEOUT, APP_URL
)
from .utils import generate_csrf_token, validate_csrf_token, encrypt_bytes_to_b64
from .storage_b2 import presign_upload, get_b2_status, delete_cv
import csv
import io
from .supabase_auth import signup as supabase_signup, signin as supabase_signin, get_user_from_token, get_google_auth_url
from .user_helpers import get_user_daily_limit
from .send_worker import send_single_message_for_user
from .assigner import assign_pending_recipients
from .sync_pool import sync_from_main_database
from .stripe_pay import create_checkout_session, verify_webhook_signature
from .config import (
    STRIPE_PUBLIC_KEY, STRIPE_WEBHOOK_SECRET, APP_URL
)
import stripe

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
from app.routers import admin, campaigns, knowledge
app.include_router(admin.router)
app.include_router(campaigns.router)
app.include_router(knowledge.router)

# --- Security: Rate Limiting ---
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- Global Exception Handlers ---
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import HTMLResponse as _HTMLResponse

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Renders branded error pages for common HTTP status codes."""
    csp_nonce = getattr(request.state, "csp_nonce", "")
    ctx = {
        "request": request,
        "csp_nonce": csp_nonce,
        "detail": str(exc.detail) if exc.detail else None,
        "title": f"{exc.status_code} Error | SaaS Sender"
    }
    if exc.status_code == 404:
        return templates.TemplateResponse("premium/404.html", ctx, status_code=404)
    if exc.status_code == 429:
        return templates.TemplateResponse("premium/429.html", ctx, status_code=429)
    # Generic fallback for other 4xx/5xx
    return templates.TemplateResponse("premium/500.html", ctx, status_code=exc.status_code)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Renders the branded 429 page for rate-limited requests."""
    csp_nonce = getattr(request.state, "csp_nonce", "")
    return templates.TemplateResponse("premium/429.html", {
        "request": request,
        "csp_nonce": csp_nonce,
        "detail": str(exc.detail) if hasattr(exc, "detail") else "Rate limit exceeded. Please slow down.",
        "title": "429 Too Many Requests | SaaS Sender"
    }, status_code=429)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catches all unhandled server-side exceptions and renders the branded 500 page."""
    LOG.exception("Unhandled exception for request %s: %s", request.url, exc)
    csp_nonce = getattr(request.state, "csp_nonce", "")
    return templates.TemplateResponse("premium/500.html", {
        "request": request,
        "csp_nonce": csp_nonce,
        "detail": None,  # Never expose raw exception details to end users
        "title": "500 Server Error | SaaS Sender"
    }, status_code=500)


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
            "daily_limit": 240,
            "is_blocked": False,
            "is_deleted": False,
            "created_at": datetime.utcnow()
        })
        local = db.users.find_one({"_id": res.inserted_id})
    
    if local:
        if local.get("is_blocked") or local.get("is_deleted"):
            LOG.warning("Authenticated user %s is blocked or deleted. Denying session.", local["email"])
            return None
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
async def session_security_middleware(request: Request, call_next):
    """
    1. Enforce Session Timeouts (Idle and Absolute).
    2. Inject session_user and csrf_token into request.state.
    3. Prevent caching of private/authenticated pages.
    """
    session = _get_session_dict(request)
    now = datetime.utcnow().timestamp()
    
    # --- 1) Session Timeout Enforcements ---
    if session:
        # Check absolute lifetime
        created_at = session.get("created_at")
        if created_at and now - created_at > SESSION_ABSOLUTE_TIMEOUT:
            LOG.info("Session absolute timeout reached. Clearing session.")
            request.session.clear()
            session = None
        
        # Check idle timeout
        if session:
            last_active = session.get("last_active")
            if last_active and now - last_active > SESSION_IDLE_TIMEOUT:
                LOG.info("Session idle timeout reached. Clearing session.")
                request.session.clear()
                session = None
            else:
                # Update last active for next time
                session["last_active"] = now
                if "created_at" not in session:
                    session["created_at"] = now
    
    # --- 2) Prepare Template context ---
    try:
        # Check Maintenance Mode (NEW)
        path = request.url.path
        is_maintenance = False
        m_msg = "System under maintenance."
        
        # Exclude static/admin from maintenance check
        if not path.startswith(("/static", "/admin", "/api/admin", "/maintenance")):
            global_settings = db.settings.find_one({"_id": "global"}) or {}
            request.state.is_maintenance = global_settings.get("maintenance_mode", False)
            request.state.maintenance_message = global_settings.get("maintenance_message", m_msg)
            request.state.broadcast_message = global_settings.get("broadcast_message", "")
            
            if request.state.is_maintenance:
                is_maintenance = True
                m_msg = request.state.maintenance_message
        else:
            request.state.is_maintenance = False
            request.state.maintenance_message = ""
            request.state.broadcast_message = ""

        if not session:
            # Re-fetch session dict in case it was cleared above
            session = _get_session_dict(request)
        
        # Ensure session exists (mostly for anonymous CSRF)
        if session is not None:
             if not session.get("session_id") and not session.get("access_token"):
                session["session_id"] = str(uuid.uuid4())
             
             csrf_sid = get_csrf_session_id(request)
             request.state.csrf_token = generate_csrf_token(csrf_sid)
             request.state.session_user = current_session_user(request)
        else:
             request.state.csrf_token = ""
             request.state.session_user = None

        # Enforce Maintenance Redirect
        if is_maintenance:
            user = request.state.session_user
            if not user or user.get("role") != "admin":
                if path != "/maintenance":
                    return RedirectResponse(url="/maintenance")

    except Exception as e:
        LOG.exception("Error while preparing template context: %s", e)
        request.state.session_user = None
        request.state.csrf_token = ""

    # Generate Nonce if not present (for template context)
    if not getattr(request.state, "csp_nonce", None):
        request.state.csp_nonce = secrets.token_hex(16)
        
    response = await call_next(request)

    # --- 3) Cache Control for Private Routes ---
    # If user is logged in or if it's a known private route, prevent caching
    is_private_route = False
    path = request.url.path
    if path.startswith(("/user/", "/settings", "/admin", "/api/", "/logout")):
        is_private_route = True
        
    if getattr(request.state, "session_user", None) or is_private_route:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
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
    # CSP with Nonce
    nonce = getattr(request.state, "csp_nonce", "")
    if not nonce:
        nonce = secrets.token_hex(16)
        request.state.csp_nonce = nonce
        
    # allow stripe/etc in CSP
    csp_policy = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://js.stripe.com; "
        f"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        f"font-src 'self' https://fonts.gstatic.com; "
        f"img-src 'self' data: https:; "
        f"connect-src 'self' https://api.ipify.org; "
        f"frame-ancestors 'self'; "
        f"frame-src 'self' https://checkout.stripe.com https://js.stripe.com; "
        f"base-uri 'self'; "
        f"form-action 'self' https://checkout.stripe.com;"
    )
    if APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = csp_policy
    else:
        # Report-only in dev or simpler policy? 
        # For now, apply same policy to test it, but maybe laxer on https
        response.headers["Content-Security-Policy"] = csp_policy

    return response

# 2. Trusted Host (Prevents Host Header attacks)
# Allow all for now, but restrict in production if domain is known
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# 3. Enforce HTTPS Redirection
if APP_ENV == "production":
    app.add_middleware(HTTPSRedirectMiddleware)

# Register SessionMiddleware LAST so it is the OUTERMOST layer
app.add_middleware(
    SessionMiddleware, 
    secret_key=SECRET_KEY, 
    https_only=(APP_ENV == "production"), 
    same_site="lax",
    session_cookie="__Host-saas_sender_session" if APP_ENV == "production" else "saas_sender_session",
    max_age=SESSION_ABSOLUTE_TIMEOUT
)



def template_ctx(request: Request):
    return {
        "request": request,
        "session_user": getattr(request.state, "session_user", None),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "is_maintenance": getattr(request.state, "is_maintenance", False),
        "maintenance_message": getattr(request.state, "maintenance_message", ""),
        "broadcast_message": getattr(request.state, "broadcast_message", ""),
        "now": datetime.utcnow(),
        "youtube_guide_url": YOUTUBE_GUIDE_URL,
        "colab_generator_url": COLAB_GENERATOR_URL,
        "csp_nonce": getattr(request.state, "csp_nonce", "")
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

@app.get("/cookies")
async def cookies(request: Request):
    ctx = template_ctx(request)
    return templates.TemplateResponse("premium/cookie.html", ctx)

@app.get("/dpa")
async def dpa(request: Request):
    ctx = template_ctx(request)
    return templates.TemplateResponse("premium/dpa.html", ctx)

@app.get("/security")
async def security(request: Request):
    ctx = template_ctx(request)
    return templates.TemplateResponse("premium/security.html", ctx)

@app.get("/pricing")
async def pricing(request: Request):
    ctx = template_ctx(request)
    return templates.TemplateResponse("premium/pricing.html", ctx)

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

@app.get("/sw.js")
async def service_worker():
    from fastapi.responses import FileResponse
    return FileResponse("app/static/sw.js")

@app.get("/manifest.json")
async def manifest():
    from fastapi.responses import FileResponse
    return FileResponse("app/static/manifest.json")

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
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    # SECURITY: Prevent enumeration/open redirect to other user dashboards
    if str(user["_id"]) != user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    return RedirectResponse(url=f"/user/{user_id}/dashboard")


@app.get("/maintenance")
def maintenance_page(request: Request):
    global_settings = db.settings.find_one({"_id": "global"}) or {}
    ctx = {
        **template_ctx(request),
        "maintenance_message": global_settings.get("maintenance_message")
    }
    return templates.TemplateResponse("premium/maintenance.html", ctx)


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
    user = current_session_user(request)
    if user and user.get("role") == "admin":
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse("premium/admin_login.html", template_ctx(request))

@app.post("/admin-login")
@limiter.limit("3/minute")  # SECURITY: Strict limit for admin login
async def admin_login_submit(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(None)):
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
        return templates.TemplateResponse("premium/admin_login.html", {**template_ctx(request), "error": "CSRF failed"})
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        # SECURITY: Regenerate session to prevent session fixation
        old_data = dict(request.session)
        request.session.clear()
        request.session.update(old_data)
        request.session["is_admin"] = True
        return RedirectResponse(url="/admin", status_code=303)
    
    return templates.TemplateResponse("premium/admin_login.html", {**template_ctx(request), "error": "Invalid credentials"})

@app.get("/login")
def login_form(request: Request):
    user = current_session_user(request)
    if user:
        if user.get("role") == "admin":
            return RedirectResponse(url="/admin")
        return RedirectResponse(url=f"/user/{user.get('_id_str', user.get('_id'))}/dashboard")
    return templates.TemplateResponse("premium/login.html", template_ctx(request))

@app.post("/login")
@limiter.limit("5/minute")  # SECURITY: Prevent brute-force attacks
def login_submit(request: Request, email: str = Form(...), password: str = Form(...), csrf: str = Form(None)):
    sid = get_csrf_session_id(request)
    if not validate_csrf_token(csrf, sid):
        ua = request.headers.get("user-agent", "unknown")
        LOG.warning("CSRF validation failed. SID: %s | UA: %s", sid, ua)
        return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": "CSRF validation failed. Please refresh and try again."})
    # SECURITY: Check for account lockout
    user_check = db.users.find_one({"email": email})
    if user_check:
        if user_check.get("locked_until") and user_check["locked_until"] > datetime.utcnow():
            remain = int((user_check["locked_until"] - datetime.utcnow()).total_seconds() / 60)
            return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": f"Account locked. Try again in {remain} minutes."})

    try:
        token_resp = supabase_signin(email=email, password=password)
        # Success - reset lockout
        if user_check:
             db.users.update_one({"_id": user_check["_id"]}, {"$set": {"failed_login_attempts": 0, "locked_until": None}})
    except Exception as e:
        # Handle 400 (Bad Request) from Supabase (wrong password etc) without full traceback
        import requests
        
        # Increment failure count
        if user_check:
             attempts = user_check.get("failed_login_attempts", 0) + 1
             update = {"failed_login_attempts": attempts}
             if attempts >= 5:
                 update["locked_until"] = datetime.utcnow() + timedelta(minutes=15)
                 LOG.warning(f"Account locked for {email} after {attempts} failed attempts")
             db.users.update_one({"_id": user_check["_id"]}, {"$set": update})
             
             if attempts >= 5:
                 return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": "Account locked due to too many failed attempts."})

        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code == 400:
            LOG.warning("Auth failure for %s: %s", email, e.response.text)
        else:
            LOG.exception("Supabase signin error")
        return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": "Login failed"})

    access_token = token_resp.get("access_token")
    refresh_token = token_resp.get("refresh_token")
    if not access_token:
        return templates.TemplateResponse("premium/login.html", {**template_ctx(request), "error": "Login failed: no token"})
    # SECURITY: Regenerate session to prevent session fixation
    if _get_session_dict(request) is None:
        request.session  # Ensure session exists
    old_data = {k: v for k, v in request.session.items() if k not in ["access_token", "refresh_token_enc"]}
    request.session.clear()
    request.session.update(old_data)
    request.session["access_token"] = access_token
    if refresh_token:
        request.session["refresh_token_enc"] = encrypt_bytes_to_b64(refresh_token.encode())
    # Map to local user and log IP
    client_ip = request.client.host
    user_info = get_user_from_token(access_token)
    local = db.users.find_one({"supabase_id": user_info["id"]})
    if not local:
        res = db.users.insert_one({
            "supabase_id": user_info["id"],
            "username": (user_info.get("email") or "").split("@")[0],
            "email": user_info.get("email"),
            "role": "user",
            "last_login_ip": client_ip,
            "created_at": datetime.utcnow()
        })
        local = db.users.find_one({"_id": res.inserted_id})
    else:
        db.users.update_one({"_id": local["_id"]}, {"$set": {"last_login_ip": client_ip}})
    
    return RedirectResponse(url=f"/user/{local['_id']}/dashboard", status_code=302)


@app.get("/login/google")
@limiter.limit("5/minute")
def google_login(request: Request):
    """Initiate Google OAuth login via Supabase"""
    # Redirect URL dynamic based on request host
    base_url = str(request.base_url).rstrip("/")
    callback_url = f"{base_url}/auth/callback"
    google_auth_url = get_google_auth_url(callback_url)
    return RedirectResponse(url=google_auth_url)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    """
    Handle OAuth callback from Supabase.
    Supabase redirects here with access_token and refresh_token in URL fragment or query params.
    """
    # Supabase sends tokens as URL fragments (#access_token=...) for implicit flow
    # OR as query params for server-side flow
    # We'll handle query params here
    access_token = request.query_params.get("access_token")
    refresh_token = request.query_params.get("refresh_token")
    error = request.query_params.get("error")
    
    if error:
        LOG.warning("OAuth error: %s", error)
        return RedirectResponse(url="/login?error=oauth_failed")
    
    if not access_token:
        # Tokens might be in fragment - render a page that extracts them via JS
        return templates.TemplateResponse("premium/oauth_callback.html", template_ctx(request))
    
    # Store tokens in session
    if _get_session_dict(request) is None:
        request.session
    request.session.clear()
    request.session["access_token"] = access_token
    if refresh_token:
        request.session["refresh_token_enc"] = encrypt_bytes_to_b64(refresh_token.encode())
    
    # Get user info and create/update local user
    client_ip = request.client.host
    user_info = get_user_from_token(access_token)
    if not user_info:
        return RedirectResponse(url="/login?error=invalid_token")
    
    local = db.users.find_one({"supabase_id": user_info["id"]})
    if not local:
        res = db.users.insert_one({
            "supabase_id": user_info["id"],
            "username": (user_info.get("email") or "").split("@")[0],
            "email": user_info.get("email"),
            "role": "user",
            "daily_limit": 240,
            "is_blocked": False,
            "is_deleted": False,
            "last_login_ip": client_ip,
            "created_at": datetime.utcnow()
        })
        local = db.users.find_one({"_id": res.inserted_id})
    else:
        db.users.update_one({"_id": local["_id"]}, {"$set": {"last_login_ip": client_ip}})
    
    return RedirectResponse(url=f"/user/{local['_id']}/dashboard", status_code=302)


@app.get("/forgot-password")
def forgot_password_form(request: Request):
    return templates.TemplateResponse("premium/forgot-password.html", template_ctx(request))

@app.post("/forgot-password")
@limiter.limit("3/minute")
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
    user = current_session_user(request)
    if user:
        return RedirectResponse(url=f"/user/{user.get('_id_str', user.get('_id'))}/dashboard")
    return templates.TemplateResponse("premium/signup.html", template_ctx(request))

@app.post("/signup")
@limiter.limit("5/minute")  # SECURITY: Prevent spam signups
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
            "is_blocked": False,
            "is_deleted": False,
            "created_at": datetime.utcnow()
        })
        local = db.users.find_one({"_id": res.inserted_id})
    return RedirectResponse(url=f"/user/{local['_id']}/dashboard", status_code=302)

@app.get("/logout")
def logout(request: Request):
    """
    Properly invalidate the session and clear cookies.
    """
    LOG.info("User logging out.")
    request.session.clear()
    
    # We redirect with 303 to ensure the browser doesn't try to cache the redirect itself
    response = RedirectResponse(url="/", status_code=303)
    
    # Explicitly clear the session cookie just in case
    response.delete_cookie(
        "saas_sender_session",
        path="/",
        domain=None,
        httponly=True,
        samesite="lax"
    )
    return response

# Presign endpoints
@app.post("/api/presign_upload")
@limiter.limit("10/minute")
async def api_presign_upload(request: Request):
    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    
    form = await request.form()
    filename = form.get("filename")
    content_type = form.get("content_type") or "application/pdf"
    allowed_types = [
        "application/pdf"
    ]
    if content_type not in allowed_types:
        return JSONResponse({"error": "Invalid content type. Only PDF files are allowed."}, status_code=400)

    try:
        res = presign_upload(filename=filename, content_type=content_type)
    except Exception as e:
        LOG.exception("presign failed")
        return JSONResponse({"error": "presign failed"}, status_code=500)
    return JSONResponse(res)

@app.post("/api/presign_complete")
@limiter.limit("10/minute")
async def api_presign_complete(request: Request):
    body = await request.json()
    key = body.get("key")
    filename = body.get("filename")
    if not key:
        return JSONResponse({"error": "key required"}, status_code=400)
    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    
    # Store old key to delete it after successful update
    old_key = user.get("cv_b2_key")
    
    db.users.update_one({"_id": user["_id"]}, {"$set": {
        "cv_b2_key": key, 
        "cv_filename": filename, 
        "cv_uploaded_at": datetime.utcnow(),
        "campaign_active": False # Stop campaign on CV update
    }})

    # Delete the old file from B2 storage if it exists and is different from the new one
    if old_key and old_key != key:
        delete_cv(old_key)

    return JSONResponse({"ok": True, "key": key})

@app.post("/api/test_send")
@limiter.limit("10/minute")
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
        LOG.error(f"Test send failed for user {user['_id']}: {str(e)}")
        # SECURITY: Do not leak internal exception details to client
        return JSONResponse({"ok": False, "error": "Failed to send test email. Check server logs."}, status_code=500)

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
    current_daily_limit = get_user_daily_limit(me)
    # Billing / Plan Status
    is_paid = bool(me.get("is_paid"))
    plan_info = {
        "name": "Outreach Pro (BYOK)" if is_paid else "Free Tier (Warmup Only)",
        "status": "Active" if is_paid else "Inactive",
        "renewal_date": me.get("subscription_expires_at").strftime("%b %d, %Y") if (is_paid and me.get("subscription_expires_at")) else "None",
        "daily_limit": current_daily_limit,
        "is_paid": is_paid
    }
    
    ctx = {**template_ctx(request), "user": me, "assigned": assigned, "pending": pending, "daily_limit": current_daily_limit, "plan": plan_info}
    try:
        return templates.TemplateResponse("premium/dashboard.html", ctx)
    except Exception:
        return templates.TemplateResponse("onboard.html", ctx)

@app.get("/api/user/me")
async def api_user_me(request: Request):
    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    
    # Refresh from DB
    me = db.users.find_one({"_id": user["_id"]})
    if not me:
        return JSONResponse({"error": "user not found"}, status_code=404)
    
    # Scrub sensitive data
    me["_id"] = str(me["_id"])
    if "credentials_base64" in me: del me["credentials_base64"]
    if "token_base64" in me: del me["token_base64"]
    if "credentials_valid" in me: del me["credentials_valid"]
    if "supabase_id" in me: del me["supabase_id"]

    # Convert dates
    for k, v in me.items():
        if isinstance(v, datetime):
            me[k] = v.isoformat()
            
    # Add warmup/limit info
    me["current_daily_limit"] = get_user_daily_limit(me)
    
    return JSONResponse(me)

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
        for key, value in r.items():
            if isinstance(value, datetime):
                r[key] = value.isoformat()
            
    return JSONResponse(recipients)


@app.get("/settings")
async def settings_get(request: Request):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    # Create a shadow copy for rendering to mask sensitive data
    me = db.users.find_one({"_id": user["_id"]})
    me["_id_str"] = str(me["_id"])
    
    ctx = {**template_ctx(request), "user": me}
    return templates.TemplateResponse("premium/settings.html", ctx)


# --- Payment Routes ---

@app.get("/payment")
def payment_page(request: Request):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    # Check if payment is enabled globally
    settings = db.settings.find_one({"_id": "global"}) or {}
    if not settings.get("payment_gateway_enabled", False) and user.get("role") != "admin":
        return RedirectResponse(url=f"/user/{user['_id']}/dashboard?error=gateway_disabled")

    # Double check Stripe configuration
    from .config import STRIPE_SECRET_KEY
    if not STRIPE_SECRET_KEY or STRIPE_SECRET_KEY.startswith("sk_test_51..."):
        LOG.error("Stripe Secret Key is missing or default in .env")
        return RedirectResponse(url=f"/user/{user['_id']}/dashboard?error=payment_config_missing")

    # Create Stripe Checkout Session
    session = create_checkout_session(
        user_id=user["_id"],
        user_email=user.get("email"),
        price_amount=10.00
    )
    
    if not session:
        return RedirectResponse(url=f"/user/{user['_id']}/dashboard?error=payment_init_failed")
    
    return RedirectResponse(url=session.url, status_code=303)

@app.post("/settings")
@limiter.limit("5/minute")
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
    if credentials_base64 and credentials_base64 != "[ENCRYPTED_DATA_HIDDEN_FOR_SECURITY]":
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
    if token_base64 and token_base64 != "[ENCRYPTED_DATA_HIDDEN_FOR_SECURITY]":
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
    if subject_template:
        # Sanitize subject
        subject_template = bleach.clean(subject_template, tags=[], strip=True)
    else:
        subject_template = "Regarding the job opening"

    if body_template:
        # 1. Simple heuristic: if no common tags, assume plain text and convert \n to <br>
        # This is extremely lightweight (one string scan and one replace)
        if not any(tag in body_template.lower() for tag in ['<p', '<div', '<br', '<li']):
             body_template = body_template.replace('\n', '<br>')

        # 2. Sanitize body (allow some basic formatting if needed)
        allowed_tags = ['b', 'i', 'u', 'strong', 'em', 'p', 'br', 'a', 'div', 'span', 'ul', 'li', 'ol']
        allowed_attrs = {'a': ['href', 'title', 'target']}
        body_template = bleach.clean(body_template, tags=allowed_tags, attributes=allowed_attrs, strip=True)
    else:
        body_template = "<p>Hi,</p><p>I am interested in the position.</p>"

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
             return templates.TemplateResponse("premium/settings.html", {**template_ctx(request), "error": "Internal error: Encryption failed", "user": user})
    
    encrypted_token = None
    if token_base64:
         try:
             encrypted_token = encrypt_bytes_to_b64(token_base64.encode())
         except Exception:
             LOG.exception("Failed to encrypt token")
             return templates.TemplateResponse("premium/settings.html", {**template_ctx(request), "error": "Internal error: Encryption failed", "user": user})

    update_data = {
        "sender_email": sender_email,
        "subject_template": subject_template,
        "body_template": body_template,
        "updated_at": datetime.utcnow(),
        "campaign_active": False # Automatically stop campaign on settings change
    }
    
    if encrypted_credentials and credentials_base64 != "[ENCRYPTED_DATA_HIDDEN_FOR_SECURITY]":
        update_data["credentials_base64"] = encrypted_credentials
        update_data["credentials_valid"] = False # Must re-validate
    if encrypted_token and token_base64 != "[ENCRYPTED_DATA_HIDDEN_FOR_SECURITY]":
        update_data["token_base64"] = encrypted_token
        update_data["credentials_valid"] = False # Must re-validate
    
    db.users.update_one({"_id": user["_id"]}, {"$set": update_data})

    
    # Refresh user for response
    user = db.users.find_one({"_id": user["_id"]})
    return templates.TemplateResponse("premium/settings.html", {**template_ctx(request), "user": user, "success": "Settings updated! Please click 'Test Connection' below to verify your Gmail API access."})

@app.post("/api/validate_credentials")
@limiter.limit("10/minute")
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
        LOG.error(f"Credential validation failed for {user['_id']}: {str(e)}")
        db.users.update_one(
            {"_id": user["_id"]}, 
            {"$set": {"credentials_valid": False, "last_validated": datetime.utcnow()}}
        )
        # SECURITY: Do not leak internal exception details
        return JSONResponse({"ok": False, "error": "Validation failed. Please check your credentials."}, status_code=400)

@app.post("/api/campaign/toggle")
@limiter.limit("20/minute")
async def api_campaign_toggle(request: Request):

    user = current_session_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    
    body = await request.json()
    active = body.get("active", False)
    
    # If starting, create a snapshot of current assets
    if active:
        # 1. CV Check
        if not user.get("cv_b2_key") or not user.get("cv_filename"):
            return JSONResponse({"error": "Please upload your CV in the Dashboard before starting."}, status_code=400)
        
        # 2. Credentials Check
        if not user.get("credentials_valid"):
             return JSONResponse({"error": "Please validate your credentials in Settings before starting."}, status_code=400)
        
        # 3. Template Check
        if not user.get("subject_template") or not user.get("body_template"):
            return JSONResponse({"error": "Please configure your email templates in Settings before starting."}, status_code=400)
        
        # 4. Payment Check
        settings = db.settings.find_one({"_id": "global"}) or {}
        if settings.get("payment_gateway_enabled", False):
             if user.get("role") != "admin":
                 expires_at = user.get("subscription_expires_at")
                 is_paid = user.get("is_paid")
                 if not is_paid or not expires_at or expires_at < datetime.utcnow():
                     return JSONResponse({"error": "Subscription required", "payment_required": True}, status_code=402)
        
        # 3. Snapshotting
        snapshot = {
            "cv_key": user.get("cv_b2_key"),
            "cv_filename": user.get("cv_filename"),
            "subject": user.get("subject_template"),
            "body": user.get("body_template"),
            "snapshot_at": datetime.utcnow()
        }
        db.users.update_one({"_id": user["_id"]}, {"$set": {"campaign_active": True, "campaign_snapshot": snapshot}})
    else:
        db.users.update_one({"_id": user["_id"]}, {"$set": {"campaign_active": False}})
    
    return JSONResponse({"ok": True, "active": active})

@app.get("/admin")
def admin_dashboard(request: Request):
    user = current_session_user(request)
    if not user: return RedirectResponse(url="/login")
    if user.get("role") != "admin": raise HTTPException(403, "Admin only")
    
    # 1. User Management Data
    users = list(db.users.find({"is_deleted": {"$ne": True}}))
    deleted_users = list(db.users.find({"is_deleted": True}))
    for u in users + deleted_users:
        u["_id_str"] = str(u["_id"])
        if not u.get("is_deleted"):
            u["assigned_count"] = db.recipients.count_documents({"assigned_to": u["_id"]})
            u["pending_capacity"] = max(0, u.get("daily_limit", 240) - u.get("daily_sent", 0))

    # 2. System Wide Stats
    pending_pool = db.recipients.count_documents({"status": "Pending"})
    day_ago = datetime.utcnow() - timedelta(days=1)
    sent_24h = db.recipients.count_documents({"status": "Sent", "sent_at": {"$gte": day_ago}})
    failed_24h = db.recipients.count_documents({"status": "Failed", "sent_at": {"$gte": day_ago}})
    
    active_users = [u for u in users if u.get("campaign_active") and u.get("credentials_valid")]
    total_capacity = sum(u.get("daily_limit", 240) for u in active_users)

    # 3. Recruiter & Deliverability Quick Stats
    total_recruiters = db.recruiters.count_documents({})
    dead_recruiters = db.recruiters.count_documents({"health": "dead"})
    suppressed_count = db.suppression.count_documents({})
    
    settings = db.settings.find_one({"_id": "global"}) or {}
    payment_active = settings.get("payment_gateway_enabled", False)

    ctx = {
        **template_ctx(request),
        "title": "Admin Dashboard",
        "users": users,
        "deleted_users": deleted_users,
        "pending_pool": pending_pool,
        "sent_24h": sent_24h,
        "failed_24h": failed_24h,
        "total_capacity": total_capacity,
        "active_users_count": len(active_users),
        "total_recruiters": total_recruiters,
        "dead_recruiters": dead_recruiters,
        "suppressed_count": suppressed_count,
        "payment_active": payment_active
    }
    return templates.TemplateResponse("premium/admin.html", ctx)


@app.post("/admin/sync_pool")
@limiter.limit("5/minute")
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
@limiter.limit("5/minute")
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

    # Create Stripe Checkout Session
    session = create_checkout_session(
        user_id=user["_id"],
        user_email=user.get("email"),
        price_amount=10.00
    )
    
    if not session:
        return RedirectResponse(url=f"/user/{user['_id']}/dashboard?error=payment_init_failed")

    # Store order attempt
    db.payments.insert_one({
        "order_id": session.id,
        "user_id": user["_id"],
        "amount": 10.00,
        "currency": "usd",
        "status": "Initiated",
        "created_at": datetime.utcnow()
    })
    
    # Redirect to Stripe Checkout
    return RedirectResponse(url=session.url, status_code=303)

@app.get("/payment/success")
async def payment_success(request: Request, session_id: str = None):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    # Optional: Verify session_id with Stripe if needed immediately
    return templates.TemplateResponse("premium/payment_success.html", {
        **template_ctx(request),
        "user": user
    })

@app.get("/payment/cancel")
async def payment_cancel(request: Request):
    user = current_session_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url=f"/user/{user['_id']}/dashboard?payment=cancelled")

@app.post("/api/payment/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    event = verify_webhook_signature(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    if not event:
        return JSONResponse({"status": "invalid signature"}, status_code=400)
    
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('metadata', {}).get('user_id')
        
        if user_id:
            # Update payment record
            db.payments.update_one(
                {"order_id": session.id},
                {"$set": {
                    "status": "Completed", 
                    "completed_at": datetime.utcnow(),
                    "stripe_customer_id": session.get('customer')
                }}
            )
            
            # Activate subscription
            expiry = datetime.utcnow() + timedelta(days=30)
            db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {
                    "is_paid": True,
                    "subscription_expires_at": expiry
                }}
            )
            LOG.info(f"Subscription activated via webhook for user {user_id}")

    return JSONResponse({"status": "success"})




# --- Admin API (Supplemental) ---
# Note: Core admin routes (list, update, delete, stats) are handled by app.routers.admin

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
        LOG.error("Failed to create user via Admin API: %s", e)
        return JSONResponse({"error": "Failed to create user. Check server logs."}, status_code=500)
    
    return JSONResponse({"error": "Could not create user. No ID returned from auth provider."}, status_code=400)

@app.post("/api/admin/users/{user_id}/restore")
async def api_admin_restore_user(user_id: str, request: Request):
    if not is_admin_request(request):
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    try:
        res = db.users.update_one(
            {"_id": ObjectId(user_id)}, 
            {"$set": {"is_deleted": False, "deleted_at": None}}
        )
        if res.matched_count == 0:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return JSONResponse({"ok": True, "message": "User restored"})
    except Exception as e:
        LOG.error("Admin restore user failed: %s", e)
        return JSONResponse({"error": "Failed to restore user. Check server logs."}, status_code=500)

@app.get("/api/admin/export_users")
def api_admin_export_users(request: Request):
    if not is_admin_request(request):
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    users = list(db.users.find({}, {"credentials_base64": 0, "token_base64": 0}))
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow(["ID", "Email", "Username", "Role", "Is Paid", "Expiry", "Campaign Active", "Daily Limit", "Created At"])
    
    for u in users:
        writer.writerow([
            str(u.get("_id")),
            u.get("email"),
            u.get("username"),
            u.get("role"),
            u.get("is_paid"),
            u.get("subscription_expires_at").isoformat() if u.get("subscription_expires_at") else "N/A",
            u.get("campaign_active"),
            u.get("daily_limit"),
            u.get("created_at").isoformat() if u.get("created_at") else "N/A"
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users_export.csv"}
    )
