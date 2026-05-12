# cli/client/schema.py
"""
HTTP client for schema registry endpoints.

Wraps the FastAPI /schema/* router.

Endpoints consumed:
    POST   /schema/sync                              → regenerate dbt contracts
    GET    /schema/{pipeline_id}/history             → version timeline
    GET    /schema/{pipeline_id}/diff                → locked vs live comparison
    POST   /schema/{pipeline_id}/approve-migration   → approve BROKEN migration
"""

from __future__ import annotations

from cli.client.http import UDEHttpClient
from cli.core.config import UDEConfig


class SchemaClient(UDEHttpClient):

    def __init__(self, config: UDEConfig) -> None:
        super().__init__(config)

    def sync(
        self,
        pipeline_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Regenerate dbt source contracts from the schema registry.
        """
        body: dict = {"dry_run": dry_run}
        if pipeline_id:
            body["pipeline_id"] = pipeline_id

        return self.post("/schema/sync", body=body)

    def history(self, pipeline_id: str, limit: int = 10) -> list[dict]:
        """
        Schema version timeline for a pipeline.
        """
        result = self.get(
            f"/schema/{pipeline_id}/history",
            params={"limit": limit},
        )
        if isinstance(result, list):
            return result
        return result.get("versions", [])

    def diff(self, pipeline_id: str) -> dict:
        """
        Compare the locked schema against what is arriving live from Pub/Sub.
        """
        return self.get(f"/schema/{pipeline_id}/diff")

    def approve_migration(self, pipeline_id: str, reason: str) -> dict:
        """
        Approve a BROKEN schema migration and unblock the pipeline.
        """
        return self.post(
            f"/schema/{pipeline_id}/approve-migration",
            body={"reason": reason},
        )