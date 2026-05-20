# cli/client/auth.py
"""
HTTP client for authentication endpoints.

Wraps the FastAPI /auth/* router.
"""

from __future__ import annotations

from cli.client.http import UDEHttpClient
from cli.core.config import UDEConfig


class AuthClient(UDEHttpClient):

    def __init__(self, config: UDEConfig) -> None:
        super().__init__(config)

    def signup(self, email: str, project_name: str) -> dict:
        """
        POST /auth/signup — create account and get API key.
        This is a public endpoint — no Bearer token required.
        """
        return self.post("/auth/signup", body={
            "email":        email,
            "project_name": project_name,
        })

    def whoami(self) -> dict:
        """GET /auth/me — show current identity."""
        return UDEHttpClient.get(self, "/auth/me")

    def rotate(self) -> dict:
        """POST /auth/key/rotate — rotate API key."""
        return self.post("/auth/key/rotate")

    def revoke(self) -> dict:
        """DELETE /auth/key — revoke API key."""
        return self.delete("/auth/key")