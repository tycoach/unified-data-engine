"""
Config resolution for the ude CLI.

Priority order (highest to lowest):
  1. --host / --port flags passed at command level
  2. UDE_HOST / UDE_PORT environment variables
  3. ~/.ude/config.yml
  4. Hardcoded defaults (localhost:8000)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".ude"
CONFIG_FILE = CONFIG_DIR / "config.yml"

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
DEFAULT_ENV = "local"


@dataclass
class UDEConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    env: str = DEFAULT_ENV          # local | staging | production
    minisky_url: str = "http://localhost:9099"
    timeout: int = 30               # seconds for HTTP requests
    extra: dict = field(default_factory=dict)

    @property
    def api_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_local(self) -> bool:
        return self.env == "local"


def load_config(
    host: str | None = None,
    port: int | None = None,
) -> UDEConfig:
    """
    Load config with full priority chain.
    Explicit args > env vars > config file > defaults.
    """
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

    return UDEConfig(
        host=resolved_host,
        port=resolved_port,
        env=resolved_env,
        minisky_url=resolved_minisky,
        timeout=resolved_timeout,
        extra=file_cfg,
    )


def _load_file() -> dict:
    """Read ~/.ude/config.yml if it exists. Return empty dict if not."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open() as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def write_config(cfg: dict) -> None:
    """Write (or overwrite) ~/.ude/config.yml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        yaml.dump(cfg, f, default_flow_style=False)


def config_exists() -> bool:
    return CONFIG_FILE.exists()