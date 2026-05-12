# cli/client/dbt.py
"""
HTTP client for dbt control plane endpoints.

Wraps the FastAPI /dbt/* router — used when the CLI needs to
trigger or query dbt runs via the API rather than as a local subprocess.

Note: Most dbt commands (run, test, snapshot, docs) invoke dbt as a
local subprocess via cli/commands/dbt.py for real-time streaming output.
This client is used for:
  - Querying run history from the API
  - Triggering remote dbt runs (when the engine is on a different host)
  - Reading run_results.json artifacts via the API

Endpoints consumed:
    POST   /dbt/run                   → trigger a dbt run remotely
    GET    /dbt/status                → last run status per pipeline
    GET    /dbt/artifacts/{pipeline}  → fetch run_results.json content
"""

from __future__ import annotations

from cli.client.http import UDEHttpClient
from cli.core.config import UDEConfig


class DbtClient(UDEHttpClient):

    def __init__(self, config: UDEConfig) -> None:
        super().__init__(config)

    def trigger_run(
        self,
        pipeline_id: str | None = None,
        select: str | None = None,
        batch_id: str | None = None,
    ) -> dict:
        """
        Trigger a dbt run via the API (remote execution).
        """
        body: dict = {}
        if pipeline_id:
            body["pipeline_id"] = pipeline_id
        if select:
            body["select"] = select
        if batch_id:
            body["batch_id"] = batch_id

        return self.post("/dbt/run", body=body)

    def get_status(self, pipeline_id: str | None = None) -> list[dict]:
        """
        Get the last dbt run status for all pipelines (or one pipeline).
        """
        params = {}
        if pipeline_id:
            params["pipeline_id"] = pipeline_id

        result = self.get("/dbt/status", params=params or None)
        if isinstance(result, list):
            return result
        return result.get("runs", [])

    def get_artifacts(self, pipeline_id: str) -> dict:
        """
        Fetch the run_results.json content for a pipeline via the API.
        """
        return self.get(f"/dbt/artifacts/{pipeline_id}")