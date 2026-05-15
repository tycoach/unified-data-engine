# api/routers/pipeline.py
"""
Pipeline management endpoints.

GET    /pipeline/                  — list all pipelines
GET    /pipeline/batches           — recent batch cycle summaries
GET    /pipeline/{id}              — full pipeline detail
GET    /pipeline/{id}/status       — quick status check
POST   /pipeline/                  — register a new pipeline (API store + filesystem)
DELETE /pipeline/{id}              — deregister a pipeline
PATCH  /pipeline/{id}/enable       — resume a paused pipeline
PATCH  /pipeline/{id}/disable      — pause a pipeline
POST   /pipeline/{id}/seed         — trigger data generator
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from config.loader import (
    load_pipelines,
    register_pipeline,
    deregister_pipeline,
    get_pipeline,
)
from engine.state.bigtable_client import BigtableClient
from engine.state.checkpoint_manager import CheckpointManager
from engine.schema.registry import SchemaRegistry

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ───────────────────────────────────────────────────────────

class PipelineRegisterRequest(BaseModel):
    """Payload for POST /pipeline/ — register a new pipeline."""
    pipeline_id:          str
    subscription_id:      str
    natural_key:          str
    scd_type:             int   # 1 or 2
    edge_case_mode:       str   = "quarantine"
    null_threshold:       float = 0.05
    late_arrival_window:  str   = "24h"
    duplicate_window:     str   = "30m"
    fields:               dict  = {}
    dbt:                  dict  = {}

    @field_validator("scd_type")
    @classmethod
    def scd_type_valid(cls, v):
        if v not in (1, 2):
            raise ValueError("scd_type must be 1 or 2")
        return v

    @field_validator("pipeline_id")
    @classmethod
    def pipeline_id_valid(cls, v):
        import re
        if not re.match(r'^[a-z][a-z0-9_]*$', v):
            raise ValueError("pipeline_id must be lowercase alphanumeric with underscores")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_pipeline_ids() -> list[str]:
    return [p["pipeline_id"] for p in load_pipelines()]


def _pipeline_config(pipeline_id: str) -> dict:
    return get_pipeline(pipeline_id) or {}


def _assert_exists(pipeline_id: str) -> None:
    if pipeline_id not in _all_pipeline_ids():
        raise HTTPException(
            status_code=404,
            detail=f"Pipeline '{pipeline_id}' not found",
        )


def _is_enabled(pipeline_id: str) -> bool:
    client = BigtableClient()
    value  = client.get(f"enabled#{pipeline_id}")
    if value is None:
        return True
    return str(value).lower() not in ("false", "0", "disabled")


def _set_enabled(pipeline_id: str, enabled: bool) -> None:
    client = BigtableClient()
    client.set(f"enabled#{pipeline_id}", str(enabled).lower())


# ── POST /pipeline/ ───────────────────────────────────────────────────────────

@router.post("/", status_code=201)
def create_pipeline(request: PipelineRegisterRequest):
    """
    Register a new pipeline with the engine.

    Persists to Bigtable (primary store) and config/pipelines/ (write-through).
    The engine picks up new pipelines on its next cycle — no restart needed.

    This is the endpoint ude pipeline new calls after scaffolding local files.
    3rd party users who install via pip never need filesystem access.
    """
    pipeline_id = request.pipeline_id

    # Check for duplicate
    existing = get_pipeline(pipeline_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline '{pipeline_id}' already exists. "
                   f"Use PATCH /pipeline/{pipeline_id} to update it.",
        )

    config = request.model_dump()
    config["registered_at"] = datetime.now(timezone.utc).isoformat()
    config["registered_via"] = "api"

    ok = register_pipeline(config)
    if not ok:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to persist pipeline '{pipeline_id}' — check engine state store",
        )

    logger.info(f"[Pipeline API] Registered new pipeline: '{pipeline_id}'")

    return {
        "pipeline_id":    pipeline_id,
        "status":         "registered",
        "registered_at":  config["registered_at"],
        "registered_via": "api",
        "message":        (
            f"Pipeline '{pipeline_id}' registered. "
            f"The engine will pick it up on its next cycle."
        ),
    }


# ── GET /pipeline/ ────────────────────────────────────────────────────────────

@router.get("/")
def list_pipelines():
    """
    List all pipelines — filesystem + API-registered combined.
    Returns fields the CLI client expects.
    """
    pipeline_ids = _all_pipeline_ids()
    registry     = SchemaRegistry()
    client       = BigtableClient()
    result       = []

    for pid in pipeline_ids:
        cfg        = _pipeline_config(pid)
        schema     = registry.get_locked(pid)
        last_batch = client.get_last_committed_batch(pid)
        checkpoint = None

        if last_batch:
            checkpoint = client.get_checkpoint(last_batch["batch_id"])

        result.append({
            "pipeline_id":        pid,
            "scd_type":           cfg.get("scd_type", 2),
            "enabled":            _is_enabled(pid),
            "schema_version":     schema["version"] if schema else None,
            "last_batch_at":      last_batch["committed_at"] if last_batch else None,
            "last_batch_records": checkpoint["records_processed"] if checkpoint else 0,
            "registered_via":     cfg.get("registered_via", "filesystem"),
            "last_batch_id":      last_batch["batch_id"] if last_batch else None,
            "last_status":        checkpoint["status"] if checkpoint else "NEVER_RUN",
        })

    return {"pipelines": result, "total": len(result)}


# ── GET /pipeline/batches ─────────────────────────────────────────────────────

@router.get("/batches")
def list_batches(
    pipeline_id: Optional[str] = Query(None),
    limit:       int           = Query(20),
):
    """Recent batch cycle summaries for ude observe watch."""
    pipeline_ids = _all_pipeline_ids()
    if pipeline_id:
        _assert_exists(pipeline_id)
        pipeline_ids = [pipeline_id]

    batches = []
    for pid in pipeline_ids:
        manager = CheckpointManager(pid)
        history = manager.history(limit=limit)

        for cp in history:
            committed_at = cp.get("checkpointed_at", "")
            batch_time   = ""
            if committed_at:
                try:
                    dt         = datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
                    batch_time = dt.strftime("%H:%M:%S")
                except ValueError:
                    batch_time = committed_at[:8]

            records_clean       = cp.get("records_processed", 0)
            records_quarantined = cp.get("records_quarantined", 0)
            total               = records_clean + records_quarantined
            quarantine_rate     = records_quarantined / total if total > 0 else 0.0

            batches.append({
                "batch_id":            cp.get("batch_id", ""),
                "pipeline_id":         pid,
                "batch_time":          batch_time,
                "records_clean":       records_clean,
                "records_quarantined": records_quarantined,
                "quarantine_rate":     quarantine_rate,
                "dbt_passed":          cp.get("dbt_passed", True),
                "snapshot_opened":     cp.get("snapshot_opened", 0),
                "schema_status":       cp.get("schema_status", "MATCH"),
                "duration_ms":         cp.get("duration_ms", 0),
            })

    batches.sort(key=lambda b: b["batch_time"], reverse=True)
    return {"batches": batches[:limit], "total": len(batches)}


# ── GET /pipeline/{pipeline_id} ───────────────────────────────────────────────

@router.get("/{pipeline_id}")
def get_pipeline_detail(pipeline_id: str):
    """Full pipeline detail — config + schema fields + last batch."""
    _assert_exists(pipeline_id)

    cfg      = _pipeline_config(pipeline_id)
    registry = SchemaRegistry()
    manager  = CheckpointManager(pipeline_id)
    schema   = registry.get_locked(pipeline_id)
    last     = manager.get_last_checkpoint()
    history  = manager.history(limit=20)

    last_batch = None
    if last:
        last_batch = {
            "batch_id":            last.get("batch_id"),
            "processed_at":        last.get("checkpointed_at"),
            "records_clean":       last.get("records_processed", 0),
            "records_quarantined": last.get("records_quarantined", 0),
            "dbt_passed":          last.get("dbt_passed", True),
            "snapshot_opened":     last.get("snapshot_opened", 0),
            "snapshot_closed":     last.get("snapshot_closed", 0),
        }

    return {
        "pipeline_id":         pipeline_id,
        "scd_type":            cfg.get("scd_type", 2),
        "enabled":             _is_enabled(pipeline_id),
        "subscription_id":     cfg.get("subscription_id", ""),
        "natural_key":         cfg.get("natural_key", ""),
        "null_threshold":      cfg.get("null_threshold", 0.05),
        "late_arrival_window": cfg.get("late_arrival_window", "24h"),
        "duplicate_window":    cfg.get("duplicate_window", "30m"),
        "edge_case_mode":      cfg.get("edge_case_mode", "quarantine"),
        "schema_version":      schema["version"] if schema else None,
        "schema_locked_at":    schema.get("locked_at") if schema else None,
        "fields":              schema.get("fields", {}) if schema else {},
        "registered_via":      cfg.get("registered_via", "filesystem"),
        "last_batch":          last_batch,
        "schema":              schema,
        "last_checkpoint":     last,
        "checkpoint_history":  history,
        "is_first_batch":      manager.is_first_batch(),
    }


# ── GET /pipeline/{pipeline_id}/status ────────────────────────────────────────

@router.get("/{pipeline_id}/status")
def pipeline_status(pipeline_id: str):
    """Quick status check."""
    _assert_exists(pipeline_id)

    manager = CheckpointManager(pipeline_id)
    last    = manager.get_last_checkpoint()

    if not last:
        return {
            "pipeline_id": pipeline_id,
            "status":      "NEVER_RUN",
            "enabled":     _is_enabled(pipeline_id),
        }

    return {
        "pipeline_id":         pipeline_id,
        "status":              last["status"],
        "enabled":             _is_enabled(pipeline_id),
        "batch_id":            last["batch_id"],
        "checkpointed_at":     last["checkpointed_at"],
        "records_processed":   last.get("records_processed", 0),
        "records_quarantined": last.get("records_quarantined", 0),
    }


# ── PATCH /pipeline/{pipeline_id}/enable ──────────────────────────────────────

@router.patch("/{pipeline_id}/enable")
def enable_pipeline(pipeline_id: str):
    """Resume a paused pipeline."""
    _assert_exists(pipeline_id)
    _set_enabled(pipeline_id, True)
    logger.info(f"[Pipeline API] '{pipeline_id}' enabled")
    return {
        "pipeline_id": pipeline_id,
        "enabled":     True,
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }


# ── PATCH /pipeline/{pipeline_id}/disable ─────────────────────────────────────

@router.patch("/{pipeline_id}/disable")
def disable_pipeline(pipeline_id: str):
    """Pause a pipeline without deleting config or data."""
    _assert_exists(pipeline_id)
    _set_enabled(pipeline_id, False)
    logger.info(f"[Pipeline API] '{pipeline_id}' disabled")
    return {
        "pipeline_id": pipeline_id,
        "enabled":     False,
        "updated_at":  datetime.now(timezone.utc).isoformat(),
        "message":     f"Pipeline '{pipeline_id}' paused — resume with PATCH /enable",
    }


# ── DELETE /pipeline/{pipeline_id} ────────────────────────────────────────────

@router.delete("/{pipeline_id}")
def delete_pipeline(pipeline_id: str):
    """
    Deregister a pipeline — removes from Bigtable and filesystem.
    Does not delete pipeline data from BigQuery.
    """
    _assert_exists(pipeline_id)

    cfg = _pipeline_config(pipeline_id)
    registered_via = cfg.get("registered_via", "filesystem")

    ok = deregister_pipeline(pipeline_id)
    if not ok:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deregister pipeline '{pipeline_id}'",
        )

    logger.info(f"[Pipeline API] Deregistered pipeline: '{pipeline_id}'")
    return {
        "pipeline_id":   pipeline_id,
        "status":        "deregistered",
        "deregistered_at": datetime.now(timezone.utc).isoformat(),
        "note":          "Pipeline data in BigQuery was not deleted.",
    }


# ── POST /pipeline/{pipeline_id}/seed ─────────────────────────────────────────

@router.post("/{pipeline_id}/seed")
def seed_pipeline(pipeline_id: str, num_records: int = 100):
    """Trigger synthetic data generator — unchanged."""
    _assert_exists(pipeline_id)

    if pipeline_id == "customers":
        import sys
        sys.path.insert(0, ".")
        from data_generator.scenarios.happy_path import (
            generate_customer,
            publish_to_minisky,
        )
        records = [generate_customer(i) for i in range(1, num_records + 1)]
        publish_to_minisky("raw.customers", records)
        return {
            "pipeline_id":       pipeline_id,
            "records_published": len(records),
            "topic":             "raw.customers",
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }

    raise HTTPException(
        status_code=400,
        detail=f"Seed not configured for pipeline '{pipeline_id}'",
    )