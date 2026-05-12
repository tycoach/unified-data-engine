# cli/client/observe.py
"""
HTTP client for observability endpoints.

Wraps Prometheus metrics scraping, log streaming, and the
batch history endpoint used by ude observe watch.

Endpoints consumed:
    GET    /metrics                          → Prometheus text format (scraped + parsed)
    GET    /pipeline/batches                 → recent batch cycle summaries
    GET    /logs/stream                      → SSE / chunked log stream
"""

from __future__ import annotations

import json
from typing import Generator

from cli.client.http import UDEHttpClient
from cli.core.config import UDEConfig


class ObserveClient(UDEHttpClient):

    def __init__(self, config: UDEConfig) -> None:
        super().__init__(config)

    def get_metrics(self, pipeline_id: str | None = None) -> dict:
        """
        Fetch and parse current Prometheus metrics from the engine API.
        """
        params = {}
        if pipeline_id:
            params["pipeline_id"] = pipeline_id

        # Hit the structured metrics endpoint (not raw Prometheus text)
        result = self.get("/metrics/structured", params=params or None)
        return result if isinstance(result, dict) else {"metrics": [], "scraped_at": "—"}

    def get_recent_batches(
        self,
        pipeline_id: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """
        Fetch the most recent batch cycle summaries.
        """
        params: dict = {"limit": limit}
        if pipeline_id:
            params["pipeline_id"] = pipeline_id

        result = self.get("/pipeline/batches", params=params)
        if isinstance(result, list):
            return result
        return result.get("batches", [])

    def stream_logs(
        self,
        pipeline_id: str | None = None,
        level: str = "INFO",
        follow: bool = True,
        lines: int = 50,
    ) -> Generator[dict, None, None]:
        """
        Stream log entries from the engine as a generator of dicts.
        """
        params: dict = {
            "level":  level,
            "follow": str(follow).lower(),
            "lines":  lines,
        }
        if pipeline_id:
            params["pipeline_id"] = pipeline_id

        for raw_line in self.stream_lines("/logs/stream", params=params):
            # Lines come as JSON objects or plain text
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError:
                # Plain text fallback — wrap it so the command layer
                # doesn't need to handle two different shapes
                yield {
                    "timestamp":   "",
                    "level":       "INFO",
                    "pipeline_id": pipeline_id or "",
                    "message":     raw_line,
                }