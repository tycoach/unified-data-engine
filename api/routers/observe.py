# api/routers/observe.py
"""
Observability endpoints — new router for CLI observe commands.

Routes:
    GET  /metrics/structured   — Prometheus metrics as structured JSON
    GET  /logs/stream          — NDJSON log stream for ude observe logs
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from prometheus_client import REGISTRY

metrics_router = APIRouter()
logs_router    = APIRouter()

logger = logging.getLogger(__name__)


# ── GET /metrics/structured ───────────────────────────────────────────────────

@metrics_router.get("/structured", summary="Structured Metrics")
def structured_metrics(
    pipeline_id: Optional[str] = Query(None, description="Filter by pipeline"),
):
    """
    Parse Prometheus metrics and return structured JSON.
    The raw /metrics endpoint stays for Prometheus scraping.
    CLI uses this for ude observe metrics.
    """
    metrics = _parse_prometheus_registry(pipeline_id=pipeline_id)
    return {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "metrics":    metrics,
        "total":      len(metrics),
    }


# ── GET /logs/stream ──────────────────────────────────────────────────────────

@logs_router.get("/stream", summary="Stream Logs")
def stream_logs(
    pipeline_id: Optional[str] = Query(None,  description="Filter by pipeline"),
    level:       str           = Query("INFO", description="Minimum log level"),
    follow:      bool          = Query(True,   description="Stream continuously"),
    lines:       int           = Query(50,     description="Historical lines before streaming"),
):
    """
    Stream engine log entries as newline-delimited JSON.
    Each line: {timestamp, level, pipeline_id, logger, message}
    """
    return StreamingResponse(
        _log_generator(
            pipeline_id=pipeline_id,
            level=level,
            follow=follow,
            lines=lines,
        ),
        media_type="application/x-ndjson",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control":          "no-cache",
            "Connection":             "keep-alive",
        },
    )


# ── Private helpers ───────────────────────────────────────────────────────────

_UDE_METRIC_PREFIXES = (
    "ude_batch",
    "ude_quarantine",
    "ude_schema",
    "ude_dbt",
    "ude_snapshot",
    "ude_checkpoint",
)

_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


def _parse_prometheus_registry(pipeline_id: Optional[str] = None) -> list[dict]:
    """Walk the Prometheus registry, return UDE metrics as structured dicts."""
    metrics = []
    try:
        for metric in REGISTRY.collect():
            if not any(metric.name.startswith(p) for p in _UDE_METRIC_PREFIXES):
                continue
            for sample in metric.samples:
                labels     = sample.labels or {}
                sample_pid = labels.get("pipeline", labels.get("pipeline_id", ""))

                if pipeline_id and sample_pid and sample_pid != pipeline_id:
                    continue

                extra_labels = {
                    k: v for k, v in labels.items()
                    if k not in ("pipeline", "pipeline_id")
                }
                labels_str = ", ".join(f'{k}="{v}"' for k, v in extra_labels.items())

                metrics.append({
                    "name":     sample.name,
                    "pipeline": sample_pid or "—",
                    "value":    sample.value,
                    "labels":   labels_str,
                })
    except Exception as e:
        logger.error(f"[Observe API] Failed to parse Prometheus registry: {e}")
    return metrics


def _log_generator(
    pipeline_id: Optional[str],
    level: str,
    follow: bool,
    lines: int,
):
    """Yield NDJSON log lines from the in-memory buffer."""
    import time

    min_level = _LEVEL_ORDER.get(level.upper(), 1)

    for entry in _log_buffer.get_recent(lines):
        if _LEVEL_ORDER.get(entry.get("level", "INFO"), 1) >= min_level:
            if pipeline_id and entry.get("pipeline_id") and entry["pipeline_id"] != pipeline_id:
                continue
            yield json.dumps(entry) + "\n"

    if not follow:
        return

    seen = _log_buffer.current_size()
    while True:
        new_entries = _log_buffer.get_since(seen)
        for entry in new_entries:
            if _LEVEL_ORDER.get(entry.get("level", "INFO"), 1) >= min_level:
                if pipeline_id and entry.get("pipeline_id") and entry["pipeline_id"] != pipeline_id:
                    continue
                yield json.dumps(entry) + "\n"
        seen += len(new_entries)
        time.sleep(0.5)


# ── In-memory log buffer ──────────────────────────────────────────────────────

class _LogBuffer:
    """Ring buffer that captures log records from the engine."""

    def __init__(self, maxsize: int = 2000) -> None:
        self._entries: list[dict] = []
        self._maxsize             = maxsize

    def append(self, entry: dict) -> None:
        self._entries.append(entry)
        if len(self._entries) > self._maxsize:
            self._entries = self._entries[-self._maxsize:]

    def get_recent(self, n: int) -> list[dict]:
        return self._entries[-n:]

    def get_since(self, index: int) -> list[dict]:
        return self._entries[index:]

    def current_size(self) -> int:
        return len(self._entries)


_log_buffer = _LogBuffer()


class _UDELogHandler(logging.Handler):
    """Python logging handler that feeds the in-memory buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            pipeline_id = getattr(record, "pipeline_id", None)
            if not pipeline_id:
                msg   = record.getMessage()
                match = re.search(r"pipeline[_\s]?(?:id)?['\"]?\s*[=:]\s*['\"]?(\w+)", msg, re.I)
                if match:
                    pipeline_id = match.group(1)

            _log_buffer.append({
                "timestamp":   datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "level":       record.levelname,
                "pipeline_id": pipeline_id or "",
                "logger":      record.name,
                "message":     record.getMessage(),
            })
        except Exception:
            pass


def install_log_handler() -> None:
    """Wire the log handler at app startup — called from api/main.py."""
    handler = _UDELogHandler()
    handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    if not any(isinstance(h, _UDELogHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)
        logger.info("[Observe API] Log handler installed")