# api/routers/schema.py
# Schema management endpoints
# GET  /schema                          — list all locked schemas
# GET  /schema/{pipeline_id}            — get locked schema for pipeline
# GET  /schema/{pipeline_id}/contract   — view current dbt source contract
# POST /schema/{pipeline_id}/approve-migration — approve a BROKEN deviation
# POST /schema/{pipeline_id}/reset      — delete locked schema (re-infer next batch)

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.schema.registry import SchemaRegistry
from engine.schema.contract_writer import write_contract, read_contract
from engine.state.bigtable_client import BigtableClient

router = APIRouter()
logger = logging.getLogger(__name__)


class MigrationApproval(BaseModel):
    reason: str
    updated_fields: dict


@router.get("/")
def list_schemas():
    """List all locked schemas."""
    registry = SchemaRegistry()
    schemas = registry.all_schemas()
    return {
        "schemas": schemas,
        "total": len(schemas),
    }


@router.get("/{pipeline_id}")
def get_schema(pipeline_id: str):
    """Get locked schema for a pipeline."""
    registry = SchemaRegistry()
    schema = registry.get_locked(pipeline_id)

    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for pipeline '{pipeline_id}'"
        )

    return schema


@router.get("/{pipeline_id}/contract")
def get_contract(pipeline_id: str):
    """View current dbt source contract (_sources.yml)."""
    contract = read_contract()
    if not contract:
        raise HTTPException(
            status_code=404,
            detail="No dbt source contract found — run a batch first"
        )
    return {"pipeline_id": pipeline_id, "contract_yaml": contract}


@router.post("/{pipeline_id}/approve-migration")
def approve_migration(pipeline_id: str, approval: MigrationApproval):
    """
    Approve a BROKEN schema deviation.
    Called by operator after reviewing quarantined batch.
    Updates schema registry and regenerates dbt source contract.
    Next batch will process against the new schema.
    """
    registry = SchemaRegistry()
    current = registry.get_locked(pipeline_id)

    if not current:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for '{pipeline_id}'"
        )

    evolved = registry.evolve(
        pipeline_id,
        approval.updated_fields,
        reason=f"OPERATOR_APPROVED: {approval.reason}",
    )

    # Update dbt source contract
    write_contract(evolved)

    # Update Bigtable schema version cache
    client = BigtableClient()
    client.set_schema_version(pipeline_id, evolved["version"])

    logger.info(
        f"[Schema API] Migration approved for '{pipeline_id}' "
        f"v{current['version']} → v{evolved['version']}"
    )

    return {
        "pipeline_id": pipeline_id,
        "old_version": current["version"],
        "new_version": evolved["version"],
        "reason": approval.reason,
        "contract_updated": True,
    }


@router.post("/{pipeline_id}/reset")
def reset_schema(pipeline_id: str):
    """
    Delete locked schema — forces re-inference on next batch.
    Use with caution — next batch will infer a fresh schema.
    """
    registry = SchemaRegistry()
    schema = registry.get_locked(pipeline_id)

    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for '{pipeline_id}'"
        )

    old_version = schema["version"]
    registry.delete(pipeline_id)

    # Clear Bigtable schema version cache
    client = BigtableClient()
    client.delete(f"schema#{pipeline_id}")

    return {
        "pipeline_id": pipeline_id,
        "deleted_version": old_version,
        "message": "Schema reset — next batch will infer fresh schema",
    }