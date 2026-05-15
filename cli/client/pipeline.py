# cli/client/pipeline.py
"""
HTTP client for pipeline endpoints.

Endpoints consumed:
    GET    /pipeline/                         → list all pipelines
    GET    /pipeline/{pipeline_id}            → get one pipeline
    POST   /pipeline/                         → register a new pipeline
    DELETE /pipeline/{pipeline_id}            → deregister a pipeline
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
        """List all registered pipelines."""
        result = UDEHttpClient.get(self, "/pipeline/")
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return result.get("pipelines", [])

    def fetch(self, pipeline_id: str) -> dict | None:
        """
        Get full detail for one pipeline.
        Returns None if not found (404).
        Named fetch() to avoid shadowing UDEHttpClient.get().
        """
        from cli.core.errors import APIError
        try:
            return UDEHttpClient.get(self, f"/pipeline/{pipeline_id}")
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def register(self, config: dict) -> dict:
        """
        Register a new pipeline with the engine via POST /pipeline/.
        """
        return self.post("/pipeline/", body=config)

    def deregister(self, pipeline_id: str) -> dict:
        """Deregister a pipeline — removes from Bigtable and filesystem."""
        return self.delete(f"/pipeline/{pipeline_id}")

    def set_enabled(self, pipeline_id: str, enabled: bool) -> dict:
        """Enable or disable a pipeline."""
        action = "enable" if enabled else "disable"
        return self.patch(f"/pipeline/{pipeline_id}/{action}")