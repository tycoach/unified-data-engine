# api/routers/auth.py
"""
Authentication endpoints — self-service API key management.

POST /auth/signup        — create account, get API key
GET  /auth/me            — show current key info
POST /auth/key/rotate    — rotate API key
DELETE /auth/key         — revoke key
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ───────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email:        str
    project_name: str


class SignupResponse(BaseModel):
    api_key:       str
    project_token: str
    project_name:  str
    email:         str
    created_at:    str
    message:       str


# ── POST /auth/signup ─────────────────────────────────────────────────────────

@router.post("/signup", response_model=SignupResponse)
def signup(request: SignupRequest):
    """
    Self-service signup — create an account and get an API key.

    No engine owner approval required. The API key scopes all
    subsequent operations to the caller's project.

    Store the returned api_key securely — it is only shown once.
    Add it to ~/.ude/config.yml or run: ude auth signup
    """
    from engine.state.bigtable_client import BigtableClient
    from cli.core.config import generate_token

    client = BigtableClient()

    # Check if email already has an account
    existing_keys = _find_keys_by_email(client, request.email)
    if existing_keys:
        raise HTTPException(
            status_code=409,
            detail=(
                f"An account already exists for {request.email}. "
                "Run: ude auth rotate to get a new key."
            ),
        )

    # Generate API key and project token
    api_key       = _generate_api_key()
    project_token = generate_token(request.project_name)
    created_at    = datetime.now(timezone.utc).isoformat()

    record = {
        "api_key":       api_key,
        "project_token": project_token,
        "project_name":  request.project_name,
        "email":         request.email,
        "created_at":    created_at,
        "last_used_at":  None,
        "active":        True,
    }

    # Store under both api_key# and email# for reverse lookup
    client.set(f"api_key#{api_key}", record)
    client.set(f"email#{request.email}", {"api_key": api_key, "project_token": project_token})

    logger.info(
        f"[Auth] New account: {request.email} "
        f"project={project_token[:16]} "
        f"key={api_key[:12]}..."
    )

    return SignupResponse(
        api_key=api_key,
        project_token=project_token,
        project_name=request.project_name,
        email=request.email,
        created_at=created_at,
        message=(
            "Account created. Save your API key — it will not be shown again. "
            "Add to ~/.ude/config.yml: api_key: " + api_key
        ),
    )


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me")
def whoami(request: Request):
    """
    Show the identity associated with the current API key.
    Requires: Authorization: Bearer <api_key>
    """
    return {
        "email":         request.state.email,
        "project_name":  request.state.project_name,
        "project_token": request.state.project_token,
        "api_key":       request.state.api_key[:12] + "...",  # truncated for safety
    }


# ── POST /auth/key/rotate ─────────────────────────────────────────────────────

@router.post("/key/rotate")
def rotate_key(request: Request):
    """
    Rotate the current API key.

    Invalidates the current key and issues a new one with the same
    project token. Update ~/.ude/config.yml with the new key.
    """
    from engine.state.bigtable_client import BigtableClient

    client    = BigtableClient()
    old_key   = request.state.api_key
    old_record = client.get(f"api_key#{old_key}")

    if not old_record:
        raise HTTPException(status_code=404, detail="Key record not found.")

    # Deactivate old key
    old_record["active"]      = False
    old_record["revoked_at"]  = datetime.now(timezone.utc).isoformat()
    old_record["revoke_reason"] = "rotated"
    client.set(f"api_key#{old_key}", old_record)

    # Issue new key — same project token and email
    new_key    = _generate_api_key()
    new_record = {
        "api_key":       new_key,
        "project_token": old_record["project_token"],
        "project_name":  old_record["project_name"],
        "email":         old_record["email"],
        "created_at":    datetime.now(timezone.utc).isoformat(),
        "last_used_at":  None,
        "active":        True,
        "rotated_from":  old_key[:12] + "...",
    }
    client.set(f"api_key#{new_key}", new_record)

    # Update email index
    client.set(
        f"email#{old_record['email']}",
        {"api_key": new_key, "project_token": old_record["project_token"]},
    )

    logger.info(
        f"[Auth] Key rotated: {old_record['email']} "
        f"old={old_key[:12]}... new={new_key[:12]}..."
    )

    return {
        "api_key":      new_key,
        "project_token": old_record["project_token"],
        "rotated_at":   new_record["created_at"],
        "message":      "Key rotated. Update ~/.ude/config.yml with the new api_key.",
    }


# ── DELETE /auth/key ──────────────────────────────────────────────────────────

@router.delete("/key")
def revoke_key(request: Request):
    """
    Revoke the current API key permanently.

    All subsequent requests with this key will return 401.
    Sign up again to get a new key.
    """
    from engine.state.bigtable_client import BigtableClient

    client  = BigtableClient()
    api_key = request.state.api_key
    record  = client.get(f"api_key#{api_key}")

    if not record:
        raise HTTPException(status_code=404, detail="Key record not found.")

    record["active"]       = False
    record["revoked_at"]   = datetime.now(timezone.utc).isoformat()
    record["revoke_reason"] = "user_requested"
    client.set(f"api_key#{api_key}", record)

    logger.info(f"[Auth] Key revoked: {record.get('email')} key={api_key[:12]}...")

    return {
        "status":     "revoked",
        "revoked_at": record["revoked_at"],
        "message":    "API key revoked. Run: ude auth signup to create a new account.",
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _generate_api_key() -> str:
    """Generate a new API key in format: ude_live_<32 hex chars>"""
    return f"ude_live_{secrets.token_hex(32)}"


def _find_keys_by_email(client, email: str) -> Optional[dict]:
    """Check if an email already has an active account."""
    try:
        record = client.get(f"email#{email}")
        if not record:
            return None
        # Verify the key is still active
        api_key = record.get("api_key")
        if not api_key:
            return None
        key_record = client.get(f"api_key#{api_key}")
        if not key_record or not key_record.get("active", True):
            return None
        return key_record
    except Exception:
        return None