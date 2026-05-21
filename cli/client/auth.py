# cli/client/auth.py
"""HTTP client for authentication endpoints."""

from __future__ import annotations
from typing import Optional
from cli.client.http import UDEHttpClient
from cli.core.config import UDEConfig


class AuthClient(UDEHttpClient):

    def __init__(self, config: UDEConfig) -> None:
        super().__init__(config)

    def signup(self, email: str, project_name: str) -> dict:
        """POST /auth/signup — public endpoint, no Bearer token needed."""
        return self.post("/auth/signup", body={
            "email":        email,
            "project_name": project_name,
        })

    def whoami(self) -> dict:
        """GET /auth/me — show current identity + expiry."""
        return UDEHttpClient.get(self, "/auth/me")

    def rotate(self) -> dict:
        """POST /auth/key/rotate — rotate API key."""
        return self.post("/auth/key/rotate")

    def revoke(self) -> dict:
        """DELETE /auth/key — revoke API key."""
        return self.delete("/auth/key")

    def list_keys(self) -> dict:
        """GET /auth/keys — list all accounts (engine owner only)."""
        return UDEHttpClient.get(self, "/auth/keys")

    def audit_log(
        self,
        limit: int = 20,
        email: Optional[str] = None,
    ) -> dict:
        """GET /auth/audit — view audit log entries."""
        params = {"limit": limit}
        if email:
            params["email"] = email
        return UDEHttpClient.get(self, "/auth/audit", params=params)