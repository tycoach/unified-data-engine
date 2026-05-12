# cli/client/pipeline.py
"""
HTTP client for pipeline endpoints.

Wraps the FastAPI /pipeline/* router.
All methods return plain dicts — command files handle presentation.

Endpoints consumed:
    GET    /pipeline                          → list all pipelines
    GET    /pipeline/{pipeline_id}            → get one pipeline
    PATCH  /pipeline/{pipeline_id}/enable     → enable a pipeline
    PATCH  /pipeline/{pipeline_id}/disable    → disable a pipeline
"""

from __future__ import annotations

from cli.client.http import UDEHttpClient
from cli.core.config import UDEConfig


class PipelineClient(UDEHttpClient):

    def __init__(self, config: UDEConfig) -> None:
        super().__init__(config)

    def list(self) -> list[dict]:
        """
        List all registered pipelines.

        Calls the base HTTP get() directly to avoid shadowing by the
        typed get(pipeline_id) method defined below.
        """
        result = UDEHttpClient.get(self, "/pipeline/")
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return result.get("pipelines", [])

    def get(self, pipeline_id: str) -> dict | None:
        """
        Get full detail for one pipeline.
        Returns None if the pipeline is not found (404).
        """
        from cli.core.errors import APIError
        try:
            return UDEHttpClient.get(self, f"/pipeline/{pipeline_id}")
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def set_enabled(self, pipeline_id: str, enabled: bool) -> dict:
        """Enable or disable a pipeline."""
        action = "enable" if enabled else "disable"
        return self.patch(f"/pipeline/{pipeline_id}/{action}")