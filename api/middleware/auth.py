# api/middleware/auth.py
"""
API key authentication middleware.

Security features:
  1. Bearer token validation on every non-public request
  2. Key expiry check (90-day TTL by default)
  3. Rate limiting on /auth/signup (5 attempts per IP per hour)
  4. Audit logging of every authenticated request to Bigtable
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ── Public routes (no auth required) ─────────────────────────────────────────

PUBLIC_ROUTES = {
    "/",
    "/health",
    "/health/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/metrics",
    "/auth/signup",
    "/auth/signup/",
}

PUBLIC_PREFIXES = ("/docs/", "/openapi")

# ── Rate limiting — in-memory (per IP, per route) ─────────────────────────────
# Simple sliding window counter. Resets on server restart.
# For production, replace with Redis-backed limiter.

_rate_limit_store: dict[str, list[float]] = defaultdict(list)

RATE_LIMITS = {
    "/auth/signup": (5, 3600),    # 5 requests per hour per IP
    "/auth/signup/": (5, 3600),
}


def _check_rate_limit(ip: str, path: str) -> bool:
    """
    Returns True if the request is allowed, False if rate limited.
    Uses a sliding window — drops timestamps older than the window.
    """
    if path not in RATE_LIMITS:
        return True

    max_requests, window_seconds = RATE_LIMITS[path]
    key     = f"{ip}:{path}"
    now     = time.time()
    cutoff  = now - window_seconds

    # Drop expired timestamps
    _rate_limit_store[key] = [
        t for t in _rate_limit_store[key] if t > cutoff
    ]

    if len(_rate_limit_store[key]) >= max_requests:
        return False

    _rate_limit_store[key].append(now)
    return True


# ── Middleware ────────────────────────────────────────────────────────────────

class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that:
    1. Rate limits public endpoints (signup)
    2. Validates Bearer tokens on protected endpoints
    3. Checks key expiry
    4. Injects identity into request.state
    5. Writes audit log entry
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip   = request.client.host if request.client else "unknown"

        # ── Rate limiting (applies to public routes too) ───────────────────
        if not _check_rate_limit(ip, path):
            logger.warning(f"[Auth] Rate limit exceeded: {ip} → {path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Too many requests. "
                        "Signup is limited to 5 attempts per hour per IP."
                    )
                },
                headers={"Retry-After": "3600"},
            )

        # ── Public routes — skip auth ──────────────────────────────────────
        if path in PUBLIC_ROUTES or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # ── Extract Bearer token ───────────────────────────────────────────
        api_key = _extract_bearer(request)
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Missing API key. "
                        "Sign up at POST /auth/signup or run: ude auth signup"
                    )
                },
            )

        # ── Validate key ───────────────────────────────────────────────────
        record = _lookup_key(api_key)
        if not record:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid API key."},
            )

        if not record.get("active", True):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "API key has been revoked. "
                        "Run: ude auth signup to create a new account."
                    )
                },
            )

        # ── Check expiry ───────────────────────────────────────────────────
        expires_at = record.get("expires_at")
        if expires_at:
            try:
                expiry_dt = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) > expiry_dt:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "detail": (
                                f"API key expired on {expires_at[:10]}. "
                                "Run: ude auth rotate to get a new key."
                            )
                        },
                    )
            except ValueError:
                pass  # malformed date — let it through

        # ── Inject identity into request.state ─────────────────────────────
        explicit_token = request.headers.get("X-UDE-Project", "")
        project_token  = (
            "__engine__"
            if explicit_token == "__engine__"
            else record.get("project_token", "")
        )

        request.state.project_token = project_token
        request.state.email         = record.get("email", "")
        request.state.project_name  = record.get("project_name", "")
        request.state.api_key       = api_key

        # ── Process request ────────────────────────────────────────────────
        start    = time.time()
        response = await call_next(request)
        duration = time.time() - start

        # ── Audit log (best effort, non-blocking) ──────────────────────────
        _write_audit_log(
            api_key=api_key,
            email=record.get("email", ""),
            project_token=project_token,
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=int(duration * 1000),
        )

        # ── Update last_used_at (best effort) ──────────────────────────────
        _touch_key(api_key, record)

        logger.debug(
            f"[Auth] {request.method} {path} {response.status_code} "
            f"{int(duration*1000)}ms — {record.get('email', '')} "
            f"key={api_key[:12]}..."
        )

        return response


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    key = auth[len("Bearer "):].strip()
    return key if key else None


def _lookup_key(api_key: str) -> Optional[dict]:
    try:
        from engine.state.bigtable_client import BigtableClient
        return BigtableClient().get(f"api_key#{api_key}")
    except Exception as exc:
        logger.error(f"[Auth] Key lookup failed: {exc}")
        return None


def _touch_key(api_key: str, record: dict) -> None:
    try:
        record["last_used_at"] = datetime.now(timezone.utc).isoformat()
        from engine.state.bigtable_client import BigtableClient
        BigtableClient().set(f"api_key#{api_key}", record)
    except Exception:
        pass


def _write_audit_log(
    api_key: str,
    email: str,
    project_token: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
) -> None:
    """
    Write an audit log entry to Bigtable.

    Key format: audit_log#{timestamp}#{truncated_key}
    Keeps a full trail of API usage for security review.
    """
    try:
        from engine.state.bigtable_client import BigtableClient
        now    = datetime.now(timezone.utc)
        ts     = now.strftime("%Y%m%dT%H%M%S%f")
        log_key = f"audit_log#{ts}#{api_key[:8]}"

        BigtableClient().set(log_key, {
            "timestamp":     now.isoformat(),
            "email":         email,
            "project_token": project_token[:20],
            "api_key":       api_key[:12] + "...",
            "method":        method,
            "path":          path,
            "status_code":   status_code,
            "duration_ms":   duration_ms,
        })
    except Exception:
        pass  # never let audit logging block a request