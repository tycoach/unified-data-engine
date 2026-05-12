# cli/client/quarantine.py
"""
HTTP client for quarantine endpoints.

Wraps the FastAPI /quarantine/* router.
All methods return plain dicts — command files handle presentation.

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
        Calls base HTTP get() directly to avoid shadowing by fetch().
        """
        params: dict = {"limit": limit}
        if pipeline_id:
            params["pipeline_id"] = pipeline_id
        if reason:
            params["reason"] = reason

        result = UDEHttpClient.get(self, "/quarantine", params=params)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return result.get("batches", [])

    def fetch(self, batch_id: str) -> dict | None:
        """
        Get full detail for one quarantined batch.
        Named fetch() to avoid shadowing UDEHttpClient.get().
        Returns None if the batch is not found (404).
        """
        from cli.core.errors import APIError
        try:
            return UDEHttpClient.get(self, f"/quarantine/{batch_id}")
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def approve(self, batch_id: str, reason: str) -> dict:
        """Release a quarantined batch for replay."""
        return self.post(
            f"/quarantine/{batch_id}/approve",
            body={"reason": reason},
        )

    def reject(self, batch_id: str, reason: str) -> dict:
        """Permanently discard a quarantined batch."""
        return self.post(
            f"/quarantine/{batch_id}/reject",
            body={"reason": reason},
        )

    def replay(self, batch_id: str) -> dict:
        """Force immediate replay of an approved batch."""
        return self.post(f"/quarantine/{batch_id}/replay")