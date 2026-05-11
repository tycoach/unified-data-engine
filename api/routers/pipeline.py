# api/routers/pipeline.py
# Pipeline management endpoints
# GET  /pipeline              — list all pipelines with last checkpoint
# GET  /pipeline/{id}         — get pipeline detail + checkpoint history
# GET  /pipeline/{id}/status  — quick status check
# POST /pipeline/{id}/seed    — trigger data generator for testing

import logging
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone

from engine.state.bigtable_client import BigtableClient
from engine.state.checkpoint_manager import CheckpointManager
from engine.schema.registry import SchemaRegistry

router = APIRouter()
logger = logging.getLogger(__name__)

# Known pipelines — in production this comes from config/pipelines/*.yml
from config.loader import load_pipelines
PIPELINES = [p["pipeline_id"] for p in load_pipelines()]


@router.get("/")
def list_pipelines():
    """List all pipelines with their last checkpoint status."""
    result = []
    client = BigtableClient()
    registry = SchemaRegistry()

    for pipeline_id in PIPELINES:
        last_offset = client.get_last_committed_batch(pipeline_id)
        schema = registry.get_locked(pipeline_id)
        checkpoint = None

        if last_offset:
            checkpoint = client.get_checkpoint(last_offset["batch_id"])

        result.append({
            "pipeline_id": pipeline_id,
            "schema_version": schema["version"] if schema else None,
            "last_batch_id": last_offset["batch_id"] if last_offset else None,
            "last_committed_at": last_offset["committed_at"] if last_offset else None,
            "last_status": checkpoint["status"] if checkpoint else "NEVER_RUN",
            "records_processed": checkpoint["records_processed"] if checkpoint else 0,
        })

    return {"pipelines": result, "total": len(result)}


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: str):
    """Get pipeline detail with checkpoint history."""
    if pipeline_id not in PIPELINES:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")

    registry = SchemaRegistry()
    manager = CheckpointManager(pipeline_id)

    schema = registry.get_locked(pipeline_id)
    history = manager.history(limit=20)
    last = manager.get_last_checkpoint()

    return {
        "pipeline_id": pipeline_id,
        "schema": schema,
        "last_checkpoint": last,
        "checkpoint_history": history,
        "is_first_batch": manager.is_first_batch(),
    }


@router.get("/{pipeline_id}/status")
def pipeline_status(pipeline_id: str):
    """Quick status check for a pipeline."""
    if pipeline_id not in PIPELINES:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")

    manager = CheckpointManager(pipeline_id)
    last = manager.get_last_checkpoint()

    if not last:
        return {"pipeline_id": pipeline_id, "status": "NEVER_RUN"}

    return {
        "pipeline_id": pipeline_id,
        "status": last["status"],
        "batch_id": last["batch_id"],
        "checkpointed_at": last["checkpointed_at"],
        "records_processed": last.get("records_processed", 0),
        "records_quarantined": last.get("records_quarantined", 0),
    }


@router.post("/{pipeline_id}/seed")
def seed_pipeline(pipeline_id: str, num_records: int = 100):
    """
    Trigger synthetic data generator for a pipeline.
    Useful for testing — publishes records to Pub/Sub.
    """
    if pipeline_id == "customers":
        import sys
        sys.path.insert(0, ".")
        from data_generator.scenarios.happy_path import publish_to_minisky, generate_customer
        import random

        records = [generate_customer(i) for i in range(1, num_records + 1)]
        publish_to_minisky("raw.customers", records)

        return {
            "pipeline_id": pipeline_id,
            "records_published": len(records),
            "topic": "raw.customers",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    raise HTTPException(
        status_code=400,
        detail=f"Seed not configured for pipeline '{pipeline_id}'"
    )