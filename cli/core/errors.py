"""
Friendly error classes for the ude CLI.

The rule: users never see a raw Python traceback.
Every exception that crosses the CLI boundary becomes one of these.
"""

from __future__ import annotations


class UDEError(Exception):
    """Base class for all ude CLI errors."""
    exit_code: int = 1


class StackNotRunningError(UDEError):
    """Raised when a command needs the FastAPI stack but it isn't up."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        super().__init__(
            f"No UDE stack found at {host}:{port}.\n"
            f"Is the stack running? Try: ude up"
        )


class MiniskyNotRunningError(UDEError):
    """Raised when MiniSky (local GCP emulator) is not reachable."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(
            f"MiniSky not reachable at {url}.\n"
            f"Start it with: minisky start"
        )


class DbtNotFoundError(UDEError):
    """Raised when dbt is not on PATH or not in the active venv."""

    def __init__(self) -> None:
        super().__init__(
            "dbt not found on PATH.\n"
            "Make sure your virtual environment is activated and dbt is installed:\n"
            "  pip install dbt-core dbt-bigquery"
        )


class NoProjectError(UDEError):
    """Raised when a command expects a UDE project but none is found."""

    def __init__(self) -> None:
        super().__init__(
            "No UDE project found in the current directory.\n"
            "Create one with: ude init"
        )


class PipelineNotFoundError(UDEError):
    """Raised when a pipeline ID doesn't exist."""

    def __init__(self, pipeline_id: str) -> None:
        self.pipeline_id = pipeline_id
        super().__init__(
            f"Pipeline '{pipeline_id}' not found.\n"
            f"List available pipelines with: ude pipeline list"
        )


class APIError(UDEError):
    """Raised when the FastAPI control plane returns an error response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"API error {status_code}: {detail}"
        )


class ConfigError(UDEError):
    """Raised for invalid or missing config values."""
    pass


class ScaffoldError(UDEError):
    """Raised when file generation fails during scaffold/init."""
    pass