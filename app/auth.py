"""
Team login via Supabase Auth. Password verification is delegated entirely to
Supabase (this app never stores or compares a password itself) -- the
session afterward is a plain signed cookie (Starlette's SessionMiddleware,
itsdangerous under the hood), not a Supabase JWT kept alive client-side,
since this is a server-rendered app with no client-side code calling
Supabase directly.

Role is stored in Supabase Auth's app_metadata (confirmed live: it comes
back in both the admin-create response and the password-grant login
response as user.app_metadata.role) -- "admin" or "member". Nothing in this
app currently branches on role; it's provisioned and available for when a
specific admin-only action needs gating.
"""
from typing import Literal

import httpx
from fastapi import Request

from app.config import SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY

Role = Literal["admin", "member"]

_TIMEOUT = 15


def _admin_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }


def verify_password_login(email: str, password: str) -> dict | None:
    """Calls Supabase's password-grant token endpoint. Returns the user dict
    (with .app_metadata.role) on success, None on any failure -- never
    raises, since a bad login is an expected, not exceptional, outcome."""
    try:
        r = httpx.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey": SUPABASE_PUBLISHABLE_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    return r.json().get("user")


def get_user_role(user: dict) -> str:
    return (user.get("app_metadata") or {}).get("role", "member")


def find_user_by_email(email: str) -> dict | None:
    r = httpx.get(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=_admin_headers(),
        params={"email": email},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    for u in r.json().get("users", []):
        if u.get("email", "").lower() == email.lower():
            return u
    return None


def create_or_update_user(email: str, password: str, role: Role) -> dict:
    """Idempotent: creates the user if they don't exist, otherwise updates
    their password + role. Used by scripts/provision_users.py, not by any
    web route -- this needs the service_role key and is an operator-run
    admin action, not something an end user triggers."""
    existing = find_user_by_email(email)
    payload = {"password": password, "email_confirm": True, "app_metadata": {"role": role}}
    if existing:
        r = httpx.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{existing['id']}",
            headers=_admin_headers(), json=payload, timeout=_TIMEOUT,
        )
    else:
        r = httpx.post(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=_admin_headers(), json={"email": email, **payload}, timeout=_TIMEOUT,
        )
    r.raise_for_status()
    return r.json()


class NotAuthenticated(Exception):
    """Raised by require_user, caught by the app-level exception handler
    registered in main.py to turn it into a redirect to /login. Empirically
    confirmed (not assumed) that a Depends()-injected function returning a
    RedirectResponse does NOT short-circuit the route -- FastAPI just hands
    that object to the route as a parameter value and the route body still
    runs. Raising an exception during dependency resolution is the pattern
    that actually prevents the route body from executing."""
    def __init__(self, next_path: str):
        self.next_path = next_path


def require_user(request: Request) -> dict:
    """FastAPI dependency -- add `user: dict = Depends(require_user)` to any
    route that needs a logged-in session. Raises NotAuthenticated (redirect
    to /login) if there's no session; otherwise returns {"email", "role"}."""
    email = request.session.get("email")
    if not email:
        raise NotAuthenticated(request.url.path)
    return {"email": email, "role": request.session.get("role", "member")}
