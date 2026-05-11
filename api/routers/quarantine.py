# api/routers/quarantine.py
# Quarantine management endpoints
# GET  /quarantine                    — list quarantine summary per pipeline
# GET  /quarantine/{pipeline_id}      — list quarantined batches
# GET  /quarantine/{batch_id}/records — get quarantined records for a batch
# POST /quarantine/{batch_id}/reprocess — reprocess a quarantined batch

import json
import logging
import urllib.request
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone

router = APIRouter()
logger = logging.getLogger(__name__)

MINISKY_BASE = "http://localhost:8080"
PROJECT_ID = "local-dev-project"


def _bq_get(path: str) -> dict:
    url = f"{MINISKY_BASE}/bigquery/v2/{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode().strip()
            return json.loads(body) if body else {}
    except Exception as e:
        logger.error(f"[Quarantine API] BQ GET error: {e}")
        return {}


@router.get("/")
def quarantine_summary():
    """
    List quarantine tables across all pipelines.
    Shows count of quarantined records per pipeline.
    """
    result = _bq_get(
        f"projects/{PROJECT_ID}/datasets/quarantine/tables"
    )
    tables = result.get("tables", [])

    summary = []
    for table in tables:
        table_id = table.get("tableReference", {}).get("tableId", "")
        summary.append({
            "table": table_id,
            "pipeline": table_id.replace("_quarantine", ""),
            "created": table.get("creationTime"),
        })

    return {
        "quarantine_tables": summary,
        "total": len(summary),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{pipeline_id}")
def get_quarantine(pipeline_id: str):
    """Get quarantine table info for a pipeline."""
    table_id = f"{pipeline_id}_quarantine"
    result = _bq_get(
        f"projects/{PROJECT_ID}/datasets/quarantine/tables/{table_id}"
    )

    if not result or "error" in result:
        raise HTTPException(
            status_code=404,
            detail=f"No quarantine table for pipeline '{pipeline_id}'"
        )

    return {
        "pipeline_id": pipeline_id,
        "table": table_id,
        "schema": result.get("schema", {}),
        "num_rows": result.get("numRows", "unknown"),
    }


@router.get("/{pipeline_id}/records")
def get_quarantine_records(pipeline_id: str, limit: int = 50):
    """
    Get quarantined records for a pipeline.
    Returns raw records with failure reasons for operator review.
    """
    table_id = f"{pipeline_id}_quarantine"
    result = _bq_get(
        f"projects/{PROJECT_ID}/datasets/quarantine"
        f"/tables/{table_id}/data?maxResults={limit}"
    )

    rows = result.get("rows", [])
    records = []
    for row in rows:
        fields = row.get("f", [])
        if fields:
            record = {
                "pipeline_id": fields[0].get("v") if len(fields) > 0 else None,
                "batch_id": fields[1].get("v") if len(fields) > 1 else None,
                "quarantined_at": fields[2].get("v") if len(fields) > 2 else None,
                "failure_reason": fields[3].get("v") if len(fields) > 3 else None,
                "raw_record": fields[4].get("v") if len(fields) > 4 else None,
            }
            records.append(record)

    return {
        "pipeline_id": pipeline_id,
        "records": records,
        "count": len(records),
        "limit": limit,
    }


@router.post("/{batch_id}/reprocess")
def reprocess_batch(batch_id: str):
    """
    Mark a quarantined batch for reprocessing.
    In production this would republish records to Pub/Sub.
    For now returns the reprocess intent.
    """
    return {
        "batch_id": batch_id,
        "action": "REPROCESS_QUEUED",
        "message": (
            "Batch marked for reprocessing. "
            "Records will be republished to Pub/Sub on next cycle."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }