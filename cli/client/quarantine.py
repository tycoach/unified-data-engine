# cli/client/quarantine.py
"""
HTTP client for quarantine endpoints.

Wraps the FastAPI /quarantine/* router.

Endpoints consumed:
    GET    /quarantine                           → list quarantined batches
    GET    /quarantine/{batch_id}                → get one batch
    POST   /quarantine/{batch_id}/approve        → release for replay
    POST   /quarantine/{batch_id}/reject         → discard permanently
    POST   /quarantine/{batch_id}/replay         → force immediate replay
"""

from __future__ import annotations

from cli.client.http import UDEHttpClient
from cli.core.config import UDEConfig


class QuarantineClient(UDEHttpClient):

    def __init__(self, config: UDEConfig) -> None:
        super().__init__(config)

    def list(
        self,
        pipeline_id: str | None = None,
        reason: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        List quarantined batches, newest first.

        Args:
            pipeline_id: Filter to a specific pipeline.
            reason:      Filter by failure reason
                         (SCHEMA_BROKEN | NULL_THRESHOLD | DUPLICATE |
                          LATE_ARRIVAL | DBT_TEST_FAILED).
            limit:       Max results to return.

        Returns:
          [
            {
              "batch_id":        "uuid-...",
              "pipeline_id":     "customers",
              "failure_reason":  "SCHEMA_BROKEN",
              "record_count":    4995,
              "quarantined_at":  "2026-03-15T02:14:00Z",
              "status":          "pending"
            },
            ...
          ]
        """
        params: dict = {"limit": limit}
        if pipeline_id:
            params["pipeline_id"] = pipeline_id
        if reason:
            params["reason"] = reason

        result = self.get("/quarantine", params=params)
        if isinstance(result, list):
            return result
        return result.get("batches", [])

    def get(self, batch_id: str) -> dict | None:
        """
        Get full detail for one quarantined batch including schema diff
        and sample records.

        Returns None if the batch is not found (404).
        """
        from cli.core.errors import APIError
        try:
            return super().get(f"/quarantine/{batch_id}")
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def approve(self, batch_id: str, reason: str) -> dict:
        """
        Release a quarantined batch for replay on the next engine cycle.

        Returns:
          {
            "batch_id": "uuid-...",
            "status":   "approved",
            "approved_at": "2026-03-15T02:30:00Z"
          }
        """
        return self.post(
            f"/quarantine/{batch_id}/approve",
            body={"reason": reason},
        )

    def reject(self, batch_id: str, reason: str) -> dict:
        """
        Permanently discard a quarantined batch.

        Returns:
          {
            "batch_id": "uuid-...",
            "status":   "rejected",
            "rejected_at": "2026-03-15T02:30:00Z"
          }
        """
        return self.post(
            f"/quarantine/{batch_id}/reject",
            body={"reason": reason},
        )

    def replay(self, batch_id: str) -> dict:
        """
        Force immediate replay of an approved batch.

        The batch must be in 'approved' status — the engine will not
        replay a pending or rejected batch.

        Returns:
          {
            "batch_id": "uuid-...",
            "status":   "replaying"    # or "not_approved"
          }
        """
        return self.post(f"/quarantine/{batch_id}/replay")