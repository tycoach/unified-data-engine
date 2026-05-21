# cli/core/config.py
"""
Config resolution for the ude CLI.

Priority order (highest to lowest):
  1. --host / --port flags
  2. UDE_HOST / UDE_PORT / UDE_PROJECT_TOKEN / UDE_API_KEY env vars
  3. ~/.ude/config.yml
  4. Hardcoded defaults (localhost:8000)
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR  = Path.home() / ".ude"
CONFIG_FILE = CONFIG_DIR / "config.yml"

DEFAULT_HOST  = "localhost"
DEFAULT_PORT  = 8000
DEFAULT_ENV   = "local"
ENGINE_OWNER_TOKEN = "__engine__"


@dataclass
class UDEConfig:
    host:          str  = DEFAULT_HOST
    port:          int  = DEFAULT_PORT
    env:           str  = DEFAULT_ENV
    minisky_url:   str  = "http://localhost:9099"
    timeout:       int  = 30
    project_token: str  = ""
    project_name:  str  = ""
    api_key:       str  = ""
    email:         str  = ""
    use_https:     bool = False
    tls_cert:      str  = ""
    tls_key:       str  = ""
    extra:         dict = field(default_factory=dict)

    @property
    def api_base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def is_local(self) -> bool:
        return self.env == "local"

    @property
    def has_project(self) -> bool:
        return bool(self.project_token)

    @property
    def is_engine_owner(self) -> bool:
        return self.project_token == ENGINE_OWNER_TOKEN

    @property
    def is_authenticated(self) -> bool:
        return bool(self.api_key)

    @property
    def has_tls(self) -> bool:
        return self.use_https and bool(self.tls_cert) and bool(self.tls_key)


def load_config(
    host: str | None = None,
    port: int | None = None,
) -> UDEConfig:
    file_cfg = _load_file()

    resolved_host = (
        host
        or os.getenv("UDE_HOST")
        or file_cfg.get("host", DEFAULT_HOST)
    )
    resolved_port = int(
        port
        or os.getenv("UDE_PORT", "")
        or file_cfg.get("port", DEFAULT_PORT)
    )
    resolved_env = (
        os.getenv("UDE_ENV")
        or file_cfg.get("env", DEFAULT_ENV)
    )
    resolved_minisky = (
        os.getenv("MINISKY_URL")
        or file_cfg.get("minisky_url", "http://localhost:9099")
    )
    resolved_timeout = int(
        os.getenv("UDE_TIMEOUT", "")
        or file_cfg.get("timeout", 30)
    )
    resolved_token = (
        os.getenv("UDE_PROJECT_TOKEN")
        or file_cfg.get("project_token", "")
    )
    resolved_api_key = (
        os.getenv("UDE_API_KEY")
        or file_cfg.get("api_key", "")
    )
    resolved_name     = file_cfg.get("project_name", "")
    resolved_email    = file_cfg.get("email", "")
    resolved_https    = file_cfg.get("use_https", False)
    resolved_tls_cert = file_cfg.get("tls_cert", "")
    resolved_tls_key  = file_cfg.get("tls_key", "")

    return UDEConfig(
        host=resolved_host,
        port=resolved_port,
        env=resolved_env,
        minisky_url=resolved_minisky,
        timeout=resolved_timeout,
        project_token=resolved_token,
        project_name=resolved_name,
        api_key=resolved_api_key,
        email=resolved_email,
        use_https=resolved_https,
        tls_cert=resolved_tls_cert,
        tls_key=resolved_tls_key,
        extra=file_cfg,
    )


def generate_token(project_name: str) -> str:
    slug = (
        project_name.lower()
        .replace(" ", "-")
        .replace("_", "-")
    )
    slug = "".join(c for c in slug if c.isalnum() or c == "-")[:20].strip("-")
    suffix = secrets.token_hex(3)
    return f"proj_{slug}-{suffix}"


def _load_file() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open() as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def write_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


def config_exists() -> bool:
    return CONFIG_FILE.exists()