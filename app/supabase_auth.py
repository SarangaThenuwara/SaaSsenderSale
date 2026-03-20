"""
Simple server-side Supabase Auth helpers.

This module uses Supabase GoTrue endpoints to:
- sign up a user (email/password)
- sign in a user (email/password) and return tokens
- fetch a user from an access_token (GET /auth/v1/user)

Notes:
- Requires SUPABASE_URL and SUPABASE_ANON_KEY in app.config
- We use the anon key for auth endpoint calls (as per Supabase docs)
"""
import os
import requests
from typing import Optional, Tuple

from .config import B2_ENDPOINT  # no-op import guard style if config loads first
from .config import MONGODB_URI  # used to ensure config import side-effects are okay

from .config import (
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
)

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    # we don't raise here to allow the app to start; but calls will error explicitly
    pass

HEADERS = {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}


def _url(path: str) -> str:
    return SUPABASE_URL.rstrip("/") + path


def signup(email: str, password: str, redirect_to: Optional[str] = None) -> dict:
    """
    Sign up user via Supabase.
    Returns the JSON response (may include access_token, refresh_token on auto-confirm).
    Raises requests.HTTPError on failure.
    """
    url = _url("/auth/v1/signup")
    if redirect_to:
        url += f"?redirect_to={redirect_to}"
    payload = {"email": email, "password": password}
    resp = requests.post(url, json=payload, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def signin(email: str, password: str) -> dict:
    """
    Sign in via password grant. Returns tokens JSON:
    {access_token, refresh_token, expires_in, token_type, ...}
    Raises requests.HTTPError on failure.
    """
    # The token endpoint expects form-encoded body for grant_type flows per GoTrue.
    url = _url("/auth/v1/token?grant_type=password")
    payload = {"email": email, "password": password}
    # Use apikey header as well
    resp = requests.post(url, json=payload, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_user_from_token(access_token: str) -> Optional[dict]:
    """
    Fetch user object from Supabase using access token.
    Returns user dict if valid, otherwise None.
    """
    if not access_token:
        return None
    url = _url("/auth/v1/user")
    headers = {"Authorization": f"Bearer {access_token}", "apikey": SUPABASE_ANON_KEY}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    return None

def get_google_auth_url(redirect_to: str) -> str:
    """
    Returns the Supabase OAuth URL to initiate Google Login.
    redirect_to: The local URL the browser should return to AFTER Supabase finishes OAuth.
    """
    # The /authorize endpoint initiates OAuth flow
    url = _url(f"/auth/v1/authorize?provider=google&redirect_to={redirect_to}")
    return url