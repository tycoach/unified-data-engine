# api/routers/auth.py
"""
Authentication endpoints.

POST   /auth/signup        — create account, get API key (90-day TTL)
GET    /auth/me            — show current key info + expiry
POST   /auth/key/rotate    — rotate API key (resets TTL)
DELETE /auth/key           — revoke key
GET    /auth/keys          — list all accounts (engine owner only)
GET    /auth/audit         — view audit log entries
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

KEY_TTL_DAYS     = 90
ENGINE_OWNER_TOK = "__engine__"


class SignupRequest(BaseModel):
    email:        str
    project_name: str


class SignupResponse(BaseModel):
    api_key:       str
    project_token: str
    project_name:  str
    email:         str
    created_at:    str
    expires_at:    str
    message:       str


# ── POST /auth/signup ─────────────────────────────────────────────────────────

@router.post("/signup", response_model=SignupResponse)
def signup(request: SignupRequest):
    """Self-service signup — returns API key (90-day TTL)."""
    from engine.state.bigtable_client import BigtableClient
    from cli.core.config import generate_token

    client   = BigtableClient()
    existing = _find_key_by_email(client, request.email)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"An account already exists for {request.email}. "
                "Run: ude auth rotate to get a new key."
            ),
        )

    api_key       = _generate_api_key()
    project_token = generate_token(request.project_name)
    now           = datetime.now(timezone.utc)
    expires_at    = (now + timedelta(days=KEY_TTL_DAYS)).isoformat()
    created_at    = now.isoformat()

    record = {
        "api_key":       api_key,
        "project_token": project_token,
        "project_name":  request.project_name,
        "email":         request.email,
        "created_at":    created_at,
        "expires_at":    expires_at,
        "last_used_at":  None,
        "active":        True,
    }

    client.set(f"api_key#{api_key}", record)
    client.set(f"email#{request.email}", {
        "api_key":       api_key,
        "project_token": project_token,
    })

    logger.info(
        f"[Auth] New account: {request.email} "
        f"project={project_token[:16]} "
        f"key={api_key[:12]}... "
        f"expires={expires_at[:10]}"
    )

    return SignupResponse(
        api_key=api_key,
        project_token=project_token,
        project_name=request.project_name,
        email=request.email,
        created_at=created_at,
        expires_at=expires_at,
        message=(
            f"Account created. Key expires {expires_at[:10]}. "
            "Save your API key — it will not be shown again. "
            f"Add to ~/.ude/config.yml: api_key: {api_key}"
        ),
    )


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me")
def whoami(request: Request):
    """Show identity + key expiry for the current API key."""
    from engine.state.bigtable_client import BigtableClient

    api_key = request.state.api_key
    record  = BigtableClient().get(f"api_key#{api_key}") or {}

    expires_at = record.get("expires_at", "")
    days_left  = _days_until_expiry(expires_at)

    return {
        "email":              request.state.email,
        "project_name":       request.state.project_name,
        "project_token":      request.state.project_token,
        "api_key":            api_key[:12] + "...",
        "created_at":         record.get("created_at", ""),
        "expires_at":         expires_at,
        "days_until_expiry":  days_left,
        "last_used_at":       record.get("last_used_at", ""),
    }


# ── POST /auth/key/rotate ─────────────────────────────────────────────────────

@router.post("/key/rotate")
def rotate_key(request: Request):
    """Rotate the current API key — resets TTL to 90 days."""
    from engine.state.bigtable_client import BigtableClient

    client     = BigtableClient()
    old_key    = request.state.api_key
    old_record = client.get(f"api_key#{old_key}")

    if not old_record:
        raise HTTPException(status_code=404, detail="Key record not found.")

    old_record["active"]        = False
    old_record["revoked_at"]    = datetime.now(timezone.utc).isoformat()
    old_record["revoke_reason"] = "rotated"
    client.set(f"api_key#{old_key}", old_record)

    new_key    = _generate_api_key()
    now        = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=KEY_TTL_DAYS)).isoformat()

    new_record = {
        "api_key":       new_key,
        "project_token": old_record["project_token"],
        "project_name":  old_record["project_name"],
        "email":         old_record["email"],
        "created_at":    now.isoformat(),
        "expires_at":    expires_at,
        "last_used_at":  None,
        "active":        True,
        "rotated_from":  old_key[:12] + "...",
    }
    client.set(f"api_key#{new_key}", new_record)
    client.set(f"email#{old_record['email']}", {
        "api_key":       new_key,
        "project_token": old_record["project_token"],
    })

    logger.info(f"[Auth] Key rotated: {old_record['email']} new={new_key[:12]}...")

    return {
        "api_key":       new_key,
        "project_token": old_record["project_token"],
        "expires_at":    expires_at,
        "rotated_at":    now.isoformat(),
        "message":       "Key rotated. Update ~/.ude/config.yml with the new api_key.",
    }


# ── DELETE /auth/key ──────────────────────────────────────────────────────────

@router.delete("/key")
def revoke_key(request: Request):
    """Revoke the current API key permanently."""
    from engine.state.bigtable_client import BigtableClient

    client  = BigtableClient()
    api_key = request.state.api_key
    record  = client.get(f"api_key#{api_key}")

    if not record:
        raise HTTPException(status_code=404, detail="Key record not found.")

    record["active"]        = False
    record["revoked_at"]    = datetime.now(timezone.utc).isoformat()
    record["revoke_reason"] = "user_requested"
    client.set(f"api_key#{api_key}", record)

    logger.info(f"[Auth] Key revoked: {record.get('email')} key={api_key[:12]}...")

    return {
        "status":     "revoked",
        "revoked_at": record["revoked_at"],
        "message":    "API key revoked. Run: ude auth signup to create a new account.",
    }


# ── GET /auth/keys ────────────────────────────────────────────────────────────

@router.get("/keys")
def list_keys(request: Request):
    """
    List all registered accounts and their key status.
    Engine owner only — requires X-UDE-Project: __engine__
    """
    if request.state.project_token != ENGINE_OWNER_TOK:
        raise HTTPException(
            status_code=403,
            detail="list-keys is restricted to the engine owner.",
        )

    from engine.state.bigtable_client import BigtableClient
    client   = BigtableClient()
    all_keys = client.all_keys()
    results  = []

    for key in all_keys:
        if not key.startswith("api_key#"):
            continue
        record = client.get(key)
        if not record or not isinstance(record, dict):
            continue

        expires_at = record.get("expires_at", "")
        days_left  = _days_until_expiry(expires_at)

        results.append({
            "email":         record.get("email", ""),
            "project_name":  record.get("project_name", ""),
            "project_token": record.get("project_token", "")[:20],
            "api_key":       record.get("api_key", "")[:12] + "...",
            "active":        record.get("active", True),
            "created_at":    record.get("created_at", ""),
            "expires_at":    expires_at,
            "days_left":     days_left,
            "last_used_at":  record.get("last_used_at", ""),
        })

    # Sort by created_at newest first
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    return {"keys": results, "total": len(results)}


# ── GET /auth/audit ───────────────────────────────────────────────────────────

@router.get("/audit")
def audit_log(
    request: Request,
    limit: int           = Query(20, description="Max entries to return"),
    email: Optional[str] = Query(None, description="Filter by email"),
):
    """
    View recent API audit log entries.

    Engine owner sees all entries.
    Regular users see only their own entries.
    """
    from engine.state.bigtable_client import BigtableClient

    client      = BigtableClient()
    all_keys    = client.all_keys()
    is_owner    = request.state.project_token == ENGINE_OWNER_TOK
    caller_email = request.state.email

    entries = []
    for key in sorted(all_keys, reverse=True):
        if not key.startswith("audit_log#"):
            continue

        record = client.get(key)
        if not record or not isinstance(record, dict):
            continue

        # Filter by caller if not engine owner
        if not is_owner and record.get("email") != caller_email:
            continue

        # Filter by email param if provided
        if email and record.get("email") != email:
            continue

        entries.append(record)
        if len(entries) >= limit:
            break

    return {
        "entries": entries,
        "total":   len(entries),
        "filtered_by_email": email,
        "scope": "all" if is_owner else "own",
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _generate_api_key() -> str:
    return f"ude_live_{secrets.token_hex(32)}"


def _find_key_by_email(client, email: str) -> Optional[dict]:
    try:
        record = client.get(f"email#{email}")
        if not record:
            return None
        api_key = record.get("api_key")
        if not api_key:
            return None
        key_record = client.get(f"api_key#{api_key}")
        if not key_record or not key_record.get("active", True):
            return None
        return key_record
    except Exception:
        return None


def _days_until_expiry(expires_at: str) -> Optional[int]:
    if not expires_at:
        return None
    try:
        expiry_dt = datetime.fromisoformat(expires_at)
        return (expiry_dt - datetime.now(timezone.utc)).days
    except ValueError:
        return None