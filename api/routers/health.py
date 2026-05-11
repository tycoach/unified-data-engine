# api/routers/health.py
# Health check endpoints
# GET /health          — overall engine health
# GET /health/state    — hot state summary (Bigtable keys)
# GET /health/minisky  — MiniSky connectivity check

import urllib.request
import logging
from fastapi import APIRouter
from datetime import datetime, timezone

from engine.state.bigtable_client import BigtableClient

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
def health_check():
    """Overall engine health."""
    state = BigtableClient()
    keys = state.all_keys()

    minisky_ok = _check_minisky()

    return {
        "status": "healthy" if minisky_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "minisky_connected": minisky_ok,
        "state_keys": len(keys),
        "engine": "UDE v2",
    }


@router.get("/state")
def state_summary():
    """Hot state summary — all Bigtable keys."""
    client = BigtableClient()
    keys = client.all_keys()
    return {
        "total_keys": len(keys),
        "keys": keys,
    }


@router.get("/minisky")
def minisky_health():
    """Check MiniSky connectivity."""
    ok = _check_minisky()
    return {
        "connected": ok,
        "endpoint": "http://localhost:8080",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _check_minisky() -> bool:
    try:
        req = urllib.request.Request(
            "http://localhost:8080/bigquery/v2/projects/local-dev-project/datasets",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False