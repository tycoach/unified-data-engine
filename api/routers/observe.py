# api/routers/observe.py
"""
Observability endpoints — new router for CLI observe commands.

Routes:
    GET  /metrics/structured   — UDE metrics scraped from Pushgateway as JSON
    GET  /logs/stream          — NDJSON log stream for ude observe logs

structured metrics scrapes Pushgateway (:9091) directly instead of
walking the FastAPI process registry. The engine pushes all UDE metrics to
Pushgateway after each batch — FastAPI's own registry only has Go/Python
internals and would always return empty for UDE-specific metrics.
"""

import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

metrics_router = APIRouter()
logs_router    = APIRouter()
logger         = logging.getLogger(__name__)

PUSHGATEWAY_URL = os.getenv("PUSHGATEWAY_URL", "http://localhost:9091")


# ── GET /metrics/structured ───────────────────────────────────────────────────

@metrics_router.get("/structured", summary="Structured Metrics")
def structured_metrics(
    pipeline_id: Optional[str] = Query(None, description="Filter by pipeline"),
):
    """
    Scrape Pushgateway and return UDE metrics as structured JSON.

    Pushgateway holds all engine batch metrics pushed after each cycle.
    Filters to ude_* metrics only — skips Go/Python process internals.

    """
    metrics, error = _scrape_pushgateway(pipeline_id=pipeline_id)

    return {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source":     "pushgateway",
        "pushgateway": PUSHGATEWAY_URL,
        "error":      error,
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


# ── Pushgateway scraper ───────────────────────────────────────────────────────

_UDE_PREFIXES = (
    "ude_batch",
    "ude_quarantine",
    "ude_schema",
    "ude_dbt",
    "ude_snapshot",
    "ude_checkpoint",
    "ude_staging",
    "ude_pubsub",
    "ude_null",
    "ude_duplicate",
    "ude_late",
    "ude_active",
)

# Metric types that produce _sum, _count, _bucket suffixes we want to skip
# in favour of the clean metric name
_SKIP_SUFFIXES = ("_bucket", "_created", "_count", "_sum", "_seconds_sum", "_duration_sum")

# Map Prometheus metric line format:
# metric_name{label="value",...} numeric_value [timestamp]
_METRIC_RE = re.compile(
    r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)'
    r'(?:\{(?P<labels>[^}]*)\})?\s+'
    r'(?P<value>[0-9eE+\-\.]+(?:Inf)?)'
)


def _scrape_pushgateway(pipeline_id: Optional[str] = None) -> tuple[list[dict], Optional[str]]:
    """
    Fetch Prometheus text from Pushgateway and parse into structured dicts.
    """
    url = f"{PUSHGATEWAY_URL}/metrics"
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/plain"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        logger.error(f"[Observe] Failed to scrape Pushgateway at {url}: {exc}")
        return [], f"Cannot reach Pushgateway at {PUSHGATEWAY_URL} — is it running?"

    metrics = []
    seen    = set()  # deduplicate histogram _sum/_count variants

    for line in raw.splitlines():
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue

        match = _METRIC_RE.match(line)
        if not match:
            continue

        name   = match.group("name")
        labels = match.group("labels") or ""
        value  = match.group("value")

        # Only UDE metrics
        if not any(name.startswith(p) for p in _UDE_PREFIXES):
            continue

        # Skip histogram internals — only keep _sum for duration metrics
        if any(name.endswith(s) for s in _SKIP_SUFFIXES):
            continue

        # Parse labels into a dict
        label_dict = _parse_labels(labels)
        pid        = label_dict.pop("pipeline_id", label_dict.pop("pipeline", ""))
        _          = label_dict.pop("instance", None)   # not useful
        _          = label_dict.pop("job", None)         # always ude_engine

        # Apply pipeline filter
        if pipeline_id and pid and pid != pipeline_id:
            continue

        # Deduplicate — histogram _sum appears once per label combo
        dedup_key = f"{name}|{pid}|{json.dumps(label_dict, sort_keys=True)}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Build remaining labels string
        labels_str = ", ".join(f'{k}="{v}"' for k, v in label_dict.items())

        # Parse numeric value
        try:
            numeric = float(value)
        except ValueError:
            numeric = 0.0

        # Clean up metric name display — strip _total suffix for counters
        display_name = name.replace("_total", "")

        metrics.append({
            "name":     display_name,
            "pipeline": pid or "—",
            "value":    numeric,
            "labels":   labels_str,
        })

    # Sort by pipeline then metric name
    metrics.sort(key=lambda m: (m["pipeline"], m["name"]))
    return metrics, None


def _parse_labels(labels_str: str) -> dict:
    """Parse 'key="val",key2="val2"' into a dict."""
    result = {}
    if not labels_str:
        return result
    for match in re.finditer(r'(\w+)="([^"]*)"', labels_str):
        result[match.group(1)] = match.group(2)
    return result


# ── Log buffer + handler ──────────────────────────────────────────────────────

_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


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


class _LogBuffer:
    """Ring buffer capturing log records from the engine."""

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