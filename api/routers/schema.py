# api/routers/schema.py
"""
Schema management endpoints.


    GET  /schema                              — list all locked schemas
    GET  /schema/{pipeline_id}                — get locked schema
    GET  /schema/{pipeline_id}/contract       — view dbt source contract
    POST /schema/{pipeline_id}/approve-migration — approve BROKEN deviation
    POST /schema/{pipeline_id}/reset          — delete locked schema

    POST /schema/sync                         — regenerate dbt contracts from registry
    GET  /schema/{pipeline_id}/history        — schema version timeline
    GET  /schema/{pipeline_id}/diff           — locked vs live comparison
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel

from engine.schema.contract_writer import read_contract, write_contract
from engine.schema.registry import SchemaRegistry
from engine.state.bigtable_client import BigtableClient

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ───────────────────────────────────────────────────────────

class MigrationApproval(BaseModel):
    reason: str
    updated_fields: dict = {}


class SyncRequest(BaseModel):
    pipeline_id: Optional[str] = None
    dry_run: bool = False


# ── GET /schema ───────────────────────────────────────────────────────────────

@router.get("/")
def list_schemas(
    x_ude_project: Optional[str] = Header(None, alias="X-UDE-Project"),
):
    """List locked schemas — scoped to project token."""
    token    = x_ude_project or "__engine__"
    registry = SchemaRegistry()
    schemas  = registry.all_schemas()

    # Engine owner sees everything; external tokens see only their schemas
    if token != "__engine__":
        schemas = [
            s for s in schemas
            if s.get("project_token") == token
        ]

    return {"schemas": schemas, "total": len(schemas)}


# ── POST /schema/sync ─────────────────────────────────────────────────────────

@router.post("/sync")
def sync_contracts(request: SyncRequest):
    """
    Regenerate dbt source contracts from the schema registry.

    For each pipeline (or a specific one), reads the locked schema
    and writes/updates dbt/models/staging/_sources.yml.

    If dry_run=True, returns what would change without writing files.
    """
    from config.loader import load_pipelines

    registry     = SchemaRegistry()
    all_pipelines = load_pipelines()

    target_pipelines = (
        [p for p in all_pipelines if p["pipeline_id"] == request.pipeline_id]
        if request.pipeline_id
        else all_pipelines
    )

    updated   = []
    unchanged = []

    for pipeline in target_pipelines:
        pid    = pipeline["pipeline_id"]
        schema = registry.get_locked(pid)

        if not schema:
            unchanged.append({"pipeline_id": pid, "version": None, "reason": "no_locked_schema"})
            continue

        current_contract = read_contract()
        version          = schema.get("version", 0)

        # Check if contract already reflects this schema version
        contract_is_current = _contract_has_version(current_contract, pid, version)

        if contract_is_current:
            unchanged.append({"pipeline_id": pid, "version": version})
            continue

        if not request.dry_run:
            write_contract(schema)
            client = BigtableClient()
            client.set_schema_version(pid, version)
            logger.info(f"[Schema API] Contract synced for '{pid}' v{version}")

        updated.append({"pipeline_id": pid, "version": version})

    return {
        "updated":   updated,
        "unchanged": unchanged,
        "dry_run":   request.dry_run,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


# ── GET /schema/{pipeline_id}/history ────────────────────────────────────────

@router.get("/{pipeline_id}/history")
def schema_history(
    pipeline_id: str,
    limit: int = Query(10, description="Max versions to return"),
):
    """
    Schema version timeline for a pipeline.

    Returns versions newest-first with change type, fields added/removed,
    and who approved the change.
    """
    registry = SchemaRegistry()
    schema   = registry.get_locked(pipeline_id)

    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for pipeline '{pipeline_id}'",
        )

    # The registry stores history as a list on the schema object
    raw_history = schema.get("history", [])

    # If no history stored (older format), build a minimal one from current state
    if not raw_history:
        raw_history = [{
            "version":        schema.get("version", 1),
            "locked_at":      schema.get("locked_at", ""),
            "change_type":    "INITIAL",
            "fields_added":   list(schema.get("fields", {}).keys()),
            "fields_removed": [],
            "approved_by":    "engine",
        }]

    # Newest first, capped at limit
    versions = sorted(
        raw_history,
        key=lambda v: v.get("version", 0),
        reverse=True,
    )[:limit]

    return {"pipeline_id": pipeline_id, "versions": versions, "total": len(versions)}


# ── GET /schema/{pipeline_id}/diff ────────────────────────────────────────────

@router.get("/{pipeline_id}/diff")
def schema_diff(pipeline_id: str):
    """
    Compare the locked schema against the most recently inferred live schema.

    The engine writes the last inferred schema to Bigtable under
    'inferred#{pipeline_id}' after every batch. This endpoint reads both
    and computes the diff so operators can preview changes before a
    BROKEN batch forces their hand.

    Returns:
        deviation:      MATCH | EVOLVED | BROKEN
        locked_version: current locked schema version
        live_version:   inferred schema version (None if no batch run yet)
        changes:        list of field-level changes
    """
    registry = SchemaRegistry()
    client   = BigtableClient()

    locked = registry.get_locked(pipeline_id)
    if not locked:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for pipeline '{pipeline_id}'",
        )

    # Read last inferred schema (written by engine after each batch inference)
    inferred = client.get(f"inferred#{pipeline_id}")

    if not inferred:
        # No batch has run yet — schema is at MATCH by definition
        return {
            "pipeline_id":    pipeline_id,
            "deviation":      "MATCH",
            "locked_version": locked.get("version"),
            "live_version":   None,
            "changes":        [],
            "message":        "No live schema yet — run a batch first",
        }

    locked_fields   = locked.get("fields", {})
    inferred_fields = inferred.get("fields", {}) if isinstance(inferred, dict) else {}

    changes   = []
    deviation = "MATCH"

    # Fields removed from live
    for field in locked_fields:
        if field not in inferred_fields:
            changes.append({
                "field":       field,
                "change":      "removed",
                "locked_type": locked_fields[field].get("type"),
                "live_type":   None,
            })
            deviation = "BROKEN"

    # Fields added in live
    for field in inferred_fields:
        if field not in locked_fields:
            changes.append({
                "field":       field,
                "change":      "added",
                "locked_type": None,
                "live_type":   inferred_fields[field].get("type"),
            })
            if deviation != "BROKEN":
                deviation = "EVOLVED"

    # Type changes
    for field in locked_fields:
        if field in inferred_fields:
            locked_type   = locked_fields[field].get("type")
            inferred_type = inferred_fields[field].get("type")
            if locked_type != inferred_type:
                is_widening = _is_type_widening(locked_type, inferred_type)
                changes.append({
                    "field":       field,
                    "change":      "widened" if is_widening else "incompatible",
                    "locked_type": locked_type,
                    "live_type":   inferred_type,
                })
                if not is_widening:
                    deviation = "BROKEN"
                elif deviation == "MATCH":
                    deviation = "EVOLVED"

    return {
        "pipeline_id":    pipeline_id,
        "deviation":      deviation,
        "locked_version": locked.get("version"),
        "live_version":   inferred.get("version") if isinstance(inferred, dict) else None,
        "changes":        changes,
    }


# ── GET /schema/{pipeline_id} ─────────────────────────────────────────────────

@router.get("/{pipeline_id}")
def get_schema(
    pipeline_id: str,
    x_ude_project: Optional[str] = Header(None, alias="X-UDE-Project"),
):
    """Get locked schema for a pipeline — unchanged."""
    registry = SchemaRegistry()
    schema   = registry.get_locked(pipeline_id)

    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for pipeline '{pipeline_id}'",
        )
    return schema


# ── GET /schema/{pipeline_id}/contract ───────────────────────────────────────

@router.get("/{pipeline_id}/contract")
def get_contract(
    pipeline_id: str,
    x_ude_project: Optional[str] = Header(None, alias="X-UDE-Project"),
):
    """View current dbt source contract — scoped to project token."""
    token = x_ude_project or "__engine__"
    contract = read_contract()
    if not contract:
        raise HTTPException(
            status_code=404,
            detail="No dbt source contract found — run a batch first",
        )
    return {"pipeline_id": pipeline_id, "contract_yaml": contract}


# ── POST /schema/{pipeline_id}/approve-migration ──────────────────────────────

@router.post("/{pipeline_id}/approve-migration")
def approve_migration(pipeline_id: str, approval: MigrationApproval):
    """
    Approve a BROKEN schema migration.

    Body shape updated — updated_fields is now optional (defaults to
    using the last inferred schema fields automatically).
    """
    registry = SchemaRegistry()
    client   = BigtableClient()
    current  = registry.get_locked(pipeline_id)

    if not current:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for '{pipeline_id}'",
        )

    # If operator didn't supply updated_fields, pull from last inferred schema
    updated_fields = approval.updated_fields
    if not updated_fields:
        inferred = client.get(f"inferred#{pipeline_id}")
        if inferred and isinstance(inferred, dict):
            updated_fields = inferred.get("fields", {})

    evolved = registry.evolve(
        pipeline_id,
        updated_fields,
        reason=f"OPERATOR_APPROVED: {approval.reason}",
    )

    write_contract(evolved)

    client.set_schema_version(pipeline_id, evolved["version"])

    logger.info(
        f"[Schema API] Migration approved for '{pipeline_id}' "
        f"v{current['version']} → v{evolved['version']}"
    )

    return {
        "pipeline_id":       pipeline_id,
        "old_version":       current["version"],
        "new_version":       evolved["version"],
        "reason":            approval.reason,
        "contract_updated":  True,
        "batches_released":  0,   # quarantine release handled by quarantine router
        "approved_at":       datetime.now(timezone.utc).isoformat(),
    }


# ── POST /schema/{pipeline_id}/reset ─────────────────────────────────────────

@router.post("/{pipeline_id}/reset")
def reset_schema(pipeline_id: str):
    """Delete locked schema — forces re-inference on next batch. Unchanged."""
    registry = SchemaRegistry()
    schema   = registry.get_locked(pipeline_id)

    if not schema:
        raise HTTPException(
            status_code=404,
            detail=f"No locked schema for pipeline '{pipeline_id}'",
        )

    old_version = schema["version"]
    registry.delete(pipeline_id)

    client = BigtableClient()
    client.delete(f"schema#{pipeline_id}")

    return {
        "pipeline_id":    pipeline_id,
        "deleted_version": old_version,
        "message":        "Schema reset — next batch will infer fresh schema",
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _contract_has_version(contract: Optional[str], pipeline_id: str, version: int) -> bool:
    """Check if the current _sources.yml already reflects this schema version."""
    if not contract:
        return False
    return f"schema v{version}" in contract or f"version: {version}" in contract


_TYPE_WIDENING_MAP = {
    ("integer", "bigint"),
    ("integer", "float"),
    ("float",   "double"),
    ("varchar", "text"),
    ("string",  "text"),
}


def _is_type_widening(from_type: Optional[str], to_type: Optional[str]) -> bool:
    """Return True if the type change is a safe widening (not a breaking change)."""
    if not from_type or not to_type:
        return False
    return (from_type.lower(), to_type.lower()) in _TYPE_WIDENING_MAP