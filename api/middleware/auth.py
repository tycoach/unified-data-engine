# api/middleware/auth.py
"""
API key authentication middleware.

Every request to the UDE API must include a valid Bearer token
in the Authorization header, except for public routes.

Public routes (no auth required):
    GET  /           — root
    GET  /health     — health check
    GET  /health/    — health check (trailing slash)
    POST /auth/signup — self-service signup
    GET  /docs       — Swagger UI
    GET  /openapi.json — OpenAPI schema
    GET  /metrics    — Prometheus scrape endpoint

All other routes require:
    Authorization: Bearer ude_live_<key>

On success, injects into request.state:
    request.state.project_token  — scopes all DB operations
    request.state.email          — caller identity
    request.state.project_name   — human-readable project name
    request.state.api_key        — the raw key (for audit logging)
"""

import logging
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Routes that don't require authentication
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

PUBLIC_PREFIXES = (
    "/docs/",
    "/openapi",
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that validates Bearer tokens on every request.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public routes
        if path in PUBLIC_ROUTES or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Extract Bearer token
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

        # Validate key
        record = _lookup_key(api_key)
        if not record:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or revoked API key."},
            )

        if not record.get("active", True):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "API key has been revoked. "
                              "Run: ude auth signup to get a new key."
                },
            )

        # Inject identity into request state
        # If caller explicitly sends X-UDE-Project: __engine__,
        # honour it as the engine owner scope (sees all pipelines).
        # The API key still validates them as authenticated.
        explicit_token = request.headers.get("X-UDE-Project", "")
        if explicit_token == "__engine__":
            project_token = "__engine__"
        else:
            project_token = record.get("project_token", "")

        request.state.project_token = project_token
        request.state.email         = record.get("email", "")
        request.state.project_name  = record.get("project_name", "")
        request.state.api_key       = api_key

        # Update last_used_at asynchronously (best effort)
        _touch_key(api_key, record)

        logger.debug(
            f"[Auth] {request.method} {path} "
            f"— key={api_key[:12]}... "
            f"project={record.get('project_token', '')[:16]}"
        )

        return await call_next(request)


def _extract_bearer(request: Request) -> Optional[str]:
    """Extract API key from Authorization: Bearer <key> header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    key = auth[len("Bearer "):].strip()
    return key if key else None


def _lookup_key(api_key: str) -> Optional[dict]:
    """Look up an API key record from Bigtable."""
    try:
        from engine.state.bigtable_client import BigtableClient
        client = BigtableClient()
        return client.get(f"api_key#{api_key}")
    except Exception as exc:
        logger.error(f"[Auth] Key lookup failed: {exc}")
        return None


def _touch_key(api_key: str, record: dict) -> None:
    """Update last_used_at on the key record (best effort, non-blocking)."""
    try:
        from datetime import datetime, timezone
        from engine.state.bigtable_client import BigtableClient
        record["last_used_at"] = datetime.now(timezone.utc).isoformat()
        BigtableClient().set(f"api_key#{api_key}", record)
    except Exception:
        pass  # never let this block the request