# api/middleware/auth.py
"""
API key authentication middleware.

Security features:
  1. Bearer token validation on every non-public request
  2. Key expiry check (90-day TTL)
  3. Rate limiting on /auth/signup (5 attempts per IP per hour)
  4. Audit logging of every authenticated request to Bigtable
  5. Suspicious activity detection (same key, 2 IPs, 60s window) → webhook
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

PUBLIC_ROUTES = {
    "/", "/health", "/health/", "/docs", "/openapi.json",
    "/redoc", "/metrics", "/auth/signup", "/auth/signup/",
}
PUBLIC_PREFIXES = ("/docs/", "/openapi")

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMITS = {
    "/auth/signup":  (5, 3600),
    "/auth/signup/": (5, 3600),
}


def _check_rate_limit(ip: str, path: str) -> bool:
    if path not in RATE_LIMITS:
        return True
    max_requests, window_seconds = RATE_LIMITS[path]
    key    = f"{ip}:{path}"
    now    = time.time()
    cutoff = now - window_seconds
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if t > cutoff]
    if len(_rate_limit_store[key]) >= max_requests:
        return False
    _rate_limit_store[key].append(now)
    return True


class APIKeyMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip   = request.client.host if request.client else "unknown"

        # Rate limiting
        if not _check_rate_limit(ip, path):
            logger.warning(f"[Auth] Rate limit exceeded: {ip} → {path}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Signup is limited to 5 per hour per IP."},
                headers={"Retry-After": "3600"},
            )

        # Public routes
        if path in PUBLIC_ROUTES or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Extract Bearer token
        api_key = _extract_bearer(request)
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key. Sign up at POST /auth/signup or run: ude auth signup"},
            )

        # Validate key
        record = _lookup_key(api_key)
        if not record:
            return JSONResponse(status_code=401, content={"detail": "Invalid API key."})

        if not record.get("active", True):
            return JSONResponse(
                status_code=401,
                content={"detail": "API key has been revoked. Run: ude auth signup to create a new account."},
            )

        # Check expiry
        expires_at = record.get("expires_at")
        if expires_at:
            try:
                if datetime.now(timezone.utc) > datetime.fromisoformat(expires_at):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": f"API key expired on {expires_at[:10]}. Run: ude auth rotate"},
                    )
            except ValueError:
                pass

        # Inject identity
        explicit_token = request.headers.get("X-UDE-Project", "")
        project_token  = "__engine__" if explicit_token == "__engine__" else record.get("project_token", "")

        request.state.project_token = project_token
        request.state.email         = record.get("email", "")
        request.state.project_name  = record.get("project_name", "")
        request.state.api_key       = api_key

        # Suspicious activity detection (non-blocking)
        try:
            from engine.notifications.webhook import check_and_fire
            check_and_fire(
                api_key=api_key,
                ip=ip,
                email=record.get("email", ""),
                project_name=record.get("project_name", ""),
            )
        except Exception:
            pass

        # Process request
        start    = time.time()
        response = await call_next(request)
        duration = time.time() - start

        # Audit log
        _write_audit_log(
            api_key=api_key,
            email=record.get("email", ""),
            project_token=project_token,
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=int(duration * 1000),
        )

        # Touch last_used_at
        _touch_key(api_key, record)

        return response


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
    api_key: str, email: str, project_token: str,
    method: str, path: str, status_code: int, duration_ms: int,
) -> None:
    try:
        from engine.state.bigtable_client import BigtableClient
        now     = datetime.now(timezone.utc)
        ts      = now.strftime("%Y%m%dT%H%M%S%f")
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
        pass