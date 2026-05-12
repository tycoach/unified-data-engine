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

        Returns a list of pipeline summary objects:
          [
            {
              "pipeline_id": "customers",
              "scd_type": 2,
              "enabled": true,
              "schema_version": 3,
              "last_batch_at": "2026-03-15T02:14:00Z",
              "last_batch_records": 4995
            },
            ...
          ]
        """
        result = self.get("/pipeline")
        # FastAPI may return {"pipelines": [...]} or a bare list
        if isinstance(result, list):
            return result
        return result.get("pipelines", [])

    def get(self, pipeline_id: str) -> dict | None:
        """
        Get full detail for one pipeline.

        Returns None if the pipeline is not found (404).
        Raises APIError for other HTTP failures.
        """
        from cli.core.errors import APIError
        try:
            return super().get(f"/pipeline/{pipeline_id}")
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def set_enabled(self, pipeline_id: str, enabled: bool) -> dict:
        """
        Enable or disable a pipeline.

        Calls PATCH /pipeline/{id}/enable or /pipeline/{id}/disable.
        Returns the updated pipeline object.
        """
        action = "enable" if enabled else "disable"
        return self.patch(f"/pipeline/{pipeline_id}/{action}")