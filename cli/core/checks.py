# cli/core/checks.py
"""
Pre-flight checks for the ude CLI.

Every command that needs a live stack calls these before doing anything.
Failures raise typed errors that get caught in main.py and rendered
as clean Rich panels — never raw tracebacks.
"""

from __future__ import annotations

import shutil
import subprocess

import httpx

from cli.core.config import UDEConfig
from cli.core.errors import (
    DbtNotFoundError,
    MiniskyNotRunningError,
    NoProjectError,
    StackNotRunningError,
)

from pathlib import Path


def assert_stack_running(cfg: UDEConfig) -> None:
    """
    Check that the FastAPI control plane is reachable.

    Uses follow_redirects=True because FastAPI redirects /health → /health/
    when the router is mounted with a trailing-slash route.
    Raises StackNotRunningError with a helpful message if not reachable.
    """
    try:
        resp = httpx.get(
            f"{cfg.api_base_url}/health",
            timeout=3.0,
            follow_redirects=True,
            verify=False,  # allow self-signed certs for local dev
        )
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        raise StackNotRunningError(cfg.host, cfg.port)


def assert_minisky_alive(cfg: UDEConfig) -> None:
    """
    Check that MiniSky (local GCP emulator) is reachable.
    Only checked when env == 'local'.
    Raises MiniskyNotRunningError if not reachable.
    """
    if not cfg.is_local:
        return

    try:
        resp = httpx.get(cfg.minisky_url, timeout=3.0, follow_redirects=True)
        _ = resp.status_code
    except (httpx.ConnectError, httpx.TimeoutException):
        raise MiniskyNotRunningError(cfg.minisky_url)


def assert_dbt_on_path() -> None:
    """
    Check that dbt is available on PATH.
    Raises DbtNotFoundError with install instructions if not.
    """
    if shutil.which("dbt") is None:
        raise DbtNotFoundError()

    try:
        result = subprocess.run(
            ["dbt", "--version"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise DbtNotFoundError()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        raise DbtNotFoundError()


def assert_project_exists() -> None:
    """
    Check that the current directory looks like a UDE project.
    We look for config/engine.yml as the canonical marker.
    Raises NoProjectError if not found.
    """
    markers = [
        Path("config/engine.yml"),
        Path("config/pipelines"),
        Path("dbt/dbt_project.yml"),
    ]
    if not any(m.exists() for m in markers):
        raise NoProjectError()


def stack_is_running(cfg: UDEConfig) -> bool:
    """
    Silent version of assert_stack_running.
    Returns True/False without raising. Used for ude status display.
    """
    try:
        assert_stack_running(cfg)
        return True
    except StackNotRunningError:
        return False


def minisky_is_alive(cfg: UDEConfig) -> bool:
    """
    Silent version of assert_minisky_alive.
    Returns True/False without raising. Used for ude status display.
    """
    try:
        assert_minisky_alive(cfg)
        return True
    except MiniskyNotRunningError:
        return False