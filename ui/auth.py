"""
ui/auth.py — Project token resolution for the Operator Dashboard



Every API call from the UI sends X-UDE-Project header with this token.
This matches the CLI behaviour introduced in v1.4.0.
"""

import os
import logging
from pathlib import Path
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".ude" / "config.yml"
_ENGINE_TOKEN = "__engine__"

# ── Token resolution ──────────────────────────────────────────────────────────

def resolve_token() -> str:
    """
    Resolve the project token in priority order:
    1. UDE_PROJECT_TOKEN env var
    2. ~/.ude/config.yml → project_token
    3. __engine__ fallback (engine owner)
    """
    # 1. Environment variable
    env_token = os.getenv("UDE_PROJECT_TOKEN", "").strip()
    if env_token:
        return env_token

    # 2. Config file
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                config = yaml.safe_load(f) or {}
            token = config.get("project_token", "").strip()
            if token:
                return token
        except Exception as e:
            logger.warning(f"[Auth] Could not read {_CONFIG_PATH}: {e}")

    # 3. Fallback — engine owner sees everything
    return _ENGINE_TOKEN


def resolve_project_name() -> str:
    """Resolve the project name for display in the sidebar."""
    if os.getenv("UDE_PROJECT_TOKEN", "").strip():
        return os.getenv("UDE_PROJECT_NAME", "Project")

    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                config = yaml.safe_load(f) or {}
            return config.get("project_name", "Engine Owner")
        except Exception:
            pass

    return "Engine Owner"


def resolve_host() -> str:
    """Resolve the API host from config or default."""
    host = os.getenv("UDE_API_HOST", "").strip()
    if host:
        return host

    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                config = yaml.safe_load(f) or {}
            h = config.get("host", "localhost")
            p = config.get("port", 8000)
            return f"http://{h}:{p}"
        except Exception:
            pass

    return "http://localhost:8000"


# ── Authenticated API client ──────────────────────────────────────────────────

class UDEClient:
    """
    Authenticated HTTP client for the UDE API.
    Automatically sends X-UDE-Project header on every request.
    All UI pages should use this instead of raw requests.get().
    """

    def __init__(self):
        self.token        = resolve_token()
        self.project_name = resolve_project_name()
        self.base_url     = resolve_host()
        self.is_engine_owner = self.token == _ENGINE_TOKEN

        self._headers = {
            "X-UDE-Project": self.token,
            "Content-Type":  "application/json",
        }

    def get(self, path: str, fallback=None, timeout: int = 5):
        """GET request with project token header."""
        try:
            r = requests.get(
                f"{self.base_url}{path}",
                headers=self._headers,
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"[UDEClient] GET {path} failed: {e}")
            return fallback

    def post(self, path: str, payload: dict = None, timeout: int = 5):
        """POST request with project token header."""
        try:
            r = requests.post(
                f"{self.base_url}{path}",
                json=payload or {},
                headers=self._headers,
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"[UDEClient] POST {path} failed: {e}")
            return {"error": str(e)}

    def token_display(self) -> str:
        """Short display version of the token."""
        if self.token == _ENGINE_TOKEN:
            return "engine owner"
        return self.token[:20] + "..." if len(self.token) > 20 else self.token


# ── Singleton — one client per Streamlit session ──────────────────────────────

def get_client() -> UDEClient:
    """
    Get or create the UDE API client for this session.
    Streamlit re-runs the script on every interaction — the client
    is lightweight so recreation is fine.
    """
    return UDEClient()