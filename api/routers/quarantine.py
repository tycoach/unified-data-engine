# api/routers/quarantine.py
"""
Quarantine management endpoints.

    GET  /quarantine                        — list quarantined batches

    GET  /quarantine/{pipeline_id}/records  — raw quarantine records for a pipeline
    POST /quarantine/{batch_id}/reprocess   — reprocess a batch (renamed to /replay)
    GET  /quarantine/{batch_id}             — full batch detail
    POST /quarantine/{batch_id}/approve     — release batch for replay
    POST /quarantine/{batch_id}/reject      — discard batch permanently
    POST /quarantine/{batch_id}/replay      — force immediate replay
"""

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from engine.state.bigtable_client import BigtableClient

router = APIRouter()
logger = logging.getLogger(__name__)

MINISKY_BASE = "http://localhost:8080"
PROJECT_ID   = "local-dev-project"


# ── Pydantic models ───────────────────────────────────────────────────────────

class QuarantineAction(BaseModel):
    reason: str


# ── BQ helpers ────────────────────────────────────────────────────────────────

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


def _read_quarantine_rows(pipeline_id: str, limit: int = 200) -> list[dict]:
    """
    Read raw rows from the BigQuery quarantine table for a pipeline.
    Maps BigQuery field array format to usable dicts.
    """
    table_id = f"{pipeline_id}_quarantine"
    result   = _bq_get(
        f"projects/{PROJECT_ID}/datasets/quarantine"
        f"/tables/{table_id}/data?maxResults={limit}"
    )

    rows    = result.get("rows", [])
    records = []

    for row in rows:
        fields = row.get("f", [])
        if fields:
            records.append({
                "pipeline_id":    fields[0].get("v") if len(fields) > 0 else None,
                "batch_id":       fields[1].get("v") if len(fields) > 1 else None,
                "quarantined_at": fields[2].get("v") if len(fields) > 2 else None,
                "failure_reason": fields[3].get("v") if len(fields) > 3 else None,
                "raw_record":     fields[4].get("v") if len(fields) > 4 else None,
            })

    return records


def _get_batch_status(batch_id: str) -> str:
    """
    Read batch action status from Bigtable.
    Keys: quarantine_action#{batch_id} → pending | approved | rejected | replayed
    """
    client = BigtableClient()
    value  = client.get(f"quarantine_action#{batch_id}")
    return str(value) if value else "pending"


def _set_batch_status(batch_id: str, status: str) -> None:
    client = BigtableClient()
    client.set(f"quarantine_action#{batch_id}", status)


def _get_batch_meta(batch_id: str) -> dict:
    """Read stored batch metadata from Bigtable."""
    client = BigtableClient()
    meta   = client.get(f"quarantine_meta#{batch_id}")
    return meta if isinstance(meta, dict) else {}


def _set_batch_meta(batch_id: str, meta: dict) -> None:
    client = BigtableClient()
    client.set(f"quarantine_meta#{batch_id}", meta)


# ── GET /quarantine ───────────────────────────────────────────────────────────

@router.get("/")
def list_quarantine(
    pipeline_id: Optional[str] = Query(None),
    reason:      Optional[str] = Query(None),
    limit:       int           = Query(20),
):
    """
    List quarantined batches — newest first.

    Rebuilt: previously returned BQ table names. Now returns actual
    batch records with failure_reason, status, and record_count —
    what the CLI (ude quarantine list) expects.
    """
    from config.loader import load_pipelines

    pipeline_ids = [p["pipeline_id"] for p in load_pipelines()]
    if pipeline_id:
        if pipeline_id not in pipeline_ids:
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
        pipeline_ids = [pipeline_id]

    batches: list[dict] = []

    for pid in pipeline_ids:
        rows = _read_quarantine_rows(pid, limit=limit * 2)

        # Group rows by batch_id to get one entry per batch
        batch_map: dict[str, dict] = {}
        for row in rows:
            bid = row.get("batch_id", "unknown")
            if bid not in batch_map:
                batch_map[bid] = {
                    "batch_id":        bid,
                    "pipeline_id":     pid,
                    "failure_reason":  row.get("failure_reason", "UNKNOWN"),
                    "quarantined_at":  row.get("quarantined_at", ""),
                    "record_count":    0,
                    "status":          _get_batch_status(bid),
                }
            batch_map[bid]["record_count"] += 1

        for batch in batch_map.values():
            # Apply reason filter
            if reason and batch["failure_reason"] != reason:
                continue
            batches.append(batch)

    # Sort newest first
    batches.sort(key=lambda b: b.get("quarantined_at", ""), reverse=True)
    result = batches[:limit]

    return {"batches": result, "total": len(result)}


# ── GET /quarantine/{batch_id} ────────────────────────────────────────────────

@router.get("/{batch_id}")
def get_quarantine_batch(batch_id: str):
    """
    Full detail for one quarantined batch — failure reason, schema diff,
    record count, and a sample of raw records.
    """
    # Read stored metadata (written by engine when quarantining a batch)
    meta = _get_batch_meta(batch_id)

    if not meta:
        # Try to reconstruct from BQ rows
        from config.loader import load_pipelines
        found_rows = []
        pipeline_id = None

        for p in load_pipelines():
            pid  = p["pipeline_id"]
            rows = _read_quarantine_rows(pid, limit=500)
            rows = [r for r in rows if r.get("batch_id") == batch_id]
            if rows:
                found_rows  = rows
                pipeline_id = pid
                break

        if not found_rows:
            raise HTTPException(
                status_code=404,
                detail=f"Batch '{batch_id}' not found in quarantine",
            )

        meta = {
            "batch_id":       batch_id,
            "pipeline_id":    pipeline_id,
            "failure_reason": found_rows[0].get("failure_reason", "UNKNOWN"),
            "quarantined_at": found_rows[0].get("quarantined_at", ""),
            "record_count":   len(found_rows),
            "schema_diff":    {},
            "sample_records": [
                json.loads(r["raw_record"]) if r.get("raw_record") else {}
                for r in found_rows[:5]
            ],
        }

    meta["status"] = _get_batch_status(batch_id)
    return meta


# ── POST /quarantine/{batch_id}/approve ───────────────────────────────────────

@router.post("/{batch_id}/approve")
def approve_batch(batch_id: str, action: QuarantineAction):
    """
    Release a quarantined batch for replay on the next engine cycle.

    Stores approved status in Bigtable. The engine reads this on the
    next cycle and replays the batch before pulling new messages.
    """
    current_status = _get_batch_status(batch_id)
    if current_status == "rejected":
        raise HTTPException(
            status_code=409,
            detail=f"Batch '{batch_id}' has already been rejected and cannot be approved",
        )

    _set_batch_status(batch_id, "approved")

    # Store approval metadata for audit log
    meta = _get_batch_meta(batch_id)
    meta.update({
        "approved_by":  "operator",
        "approved_at":  datetime.now(timezone.utc).isoformat(),
        "approval_reason": action.reason,
    })
    _set_batch_meta(batch_id, meta)

    logger.info(f"[Quarantine API] Batch '{batch_id}' approved: {action.reason}")

    return {
        "batch_id":    batch_id,
        "status":      "approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "reason":      action.reason,
    }


# ── POST /quarantine/{batch_id}/reject ────────────────────────────────────────

@router.post("/{batch_id}/reject")
def reject_batch(batch_id: str, action: QuarantineAction):
    """
    Permanently discard a quarantined batch.

    Marks the batch as rejected in Bigtable. The batch will not be
    replayed. Records remain in BigQuery for audit purposes.
    """
    current_status = _get_batch_status(batch_id)
    if current_status == "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Batch '{batch_id}' is already approved — cannot reject",
        )

    _set_batch_status(batch_id, "rejected")

    meta = _get_batch_meta(batch_id)
    meta.update({
        "rejected_by":     "operator",
        "rejected_at":     datetime.now(timezone.utc).isoformat(),
        "rejection_reason": action.reason,
    })
    _set_batch_meta(batch_id, meta)

    logger.info(f"[Quarantine API] Batch '{batch_id}' rejected: {action.reason}")

    return {
        "batch_id":    batch_id,
        "status":      "rejected",
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "reason":      action.reason,
    }


# ── POST /quarantine/{batch_id}/replay ────────────────────────────────────────

@router.post("/{batch_id}/replay")
def replay_batch(batch_id: str):
    """
    Force immediate replay of an approved batch.

    The batch must be in 'approved' status. Sets status to 'replaying'
    and writes a replay flag the engine reads on its next poll.
    """
    current_status = _get_batch_status(batch_id)

    if current_status != "approved":
        return {
            "batch_id": batch_id,
            "status":   "not_approved",
            "message":  f"Batch is '{current_status}' — approve it first: POST /quarantine/{batch_id}/approve",
        }

    _set_batch_status(batch_id, "replaying")

    # Write replay flag — engine polls quarantine_replay# keys on each cycle
    client = BigtableClient()
    client.set(
        f"quarantine_replay#{batch_id}",
        datetime.now(timezone.utc).isoformat(),
    )

    logger.info(f"[Quarantine API] Replay triggered for batch '{batch_id}'")

    return {
        "batch_id":     batch_id,
        "status":       "replaying",
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "message":      "Replay triggered — monitor progress with: ude observe watch",
    }


# ── GET /quarantine/{pipeline_id}/records ────────────────────────────────────

@router.get("/{pipeline_id}/records")
def get_quarantine_records(pipeline_id: str, limit: int = 50):
    """
    Raw quarantine records for a pipeline.
    Kept from original for Streamlit UI backward compatibility.
    """
    records = _read_quarantine_rows(pipeline_id, limit=limit)
    return {
        "pipeline_id": pipeline_id,
        "records":     records,
        "count":       len(records),
        "limit":       limit,
    }


# ── POST /quarantine/{batch_id}/reprocess ────────────────────────────────────

@router.post("/{batch_id}/reprocess")
def reprocess_batch(batch_id: str):
    """
    Legacy reprocess endpoint — kept for backward compatibility.
    New code should use POST /quarantine/{batch_id}/replay instead.
    """
    return {
        "batch_id":  batch_id,
        "action":    "REPROCESS_QUEUED",
        "message":   "Use POST /quarantine/{batch_id}/replay for the updated interface.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }