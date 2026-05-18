# api/routers/dbt.py
# dbt control endpoints
# POST /dbt/run/{pipeline_id}   — manually trigger dbt run for a pipeline
# GET  /dbt/status              — last dbt run results
# GET  /dbt/lineage/{pipeline}  — model lineage from manifest.json
# GET  /dbt/artifacts           — list available dbt artifacts

import logging
from fastapi import APIRouter, Header, HTTPException, BackgroundTasks
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, timezone

from engine.dbt_runner.runner import DbtRunner
from engine.dbt_runner.results import DbtResults

router = APIRouter()
logger = logging.getLogger(__name__)

# Track last run result in memory (stateless — use Bigtable in production)
_last_run: dict = {}


class DbtRunRequest(BaseModel):
    batch_id: str
    scd_type: int = 2
    target: str = "dev"


@router.post("/run/{pipeline_id}")
def trigger_dbt_run(
    pipeline_id: str,
    request: DbtRunRequest,
    background_tasks: BackgroundTasks,
):
    """
    Manually trigger a dbt pipeline run for a pipeline.
    Runs in background — poll /dbt/status for result.
    """
    global _last_run

    _last_run = {
        "pipeline_id": pipeline_id,
        "batch_id": request.batch_id,
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    def run_dbt():
        global _last_run
        runner = DbtRunner(target=request.target)
        result = runner.run_full_pipeline(
            pipeline_id=pipeline_id,
            batch_id=request.batch_id,
            scd_type=request.scd_type,
        )
        _last_run.update({
            "status": "COMPLETE" if result["success"] else "FAILED",
            "success": result["success"],
            "failed_at": result.get("failed_at"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[dbt API] Run complete: {_last_run['status']}")

    background_tasks.add_task(run_dbt)

    return {
        "pipeline_id": pipeline_id,
        "batch_id": request.batch_id,
        "status": "RUNNING",
        "message": "dbt run triggered — poll /dbt/status for result",
    }


@router.get("/status")
def dbt_status():
    """Get last dbt run status."""
    if not _last_run:
        return {"status": "NO_RUNS", "message": "No dbt runs triggered yet"}
    return _last_run


@router.get("/results")
def dbt_results():
    """Parse and return last dbt run_results.json."""
    results = DbtResults.parse_run_results()
    if not results:
        raise HTTPException(
            status_code=404,
            detail="No run_results.json found — run dbt first"
        )
    return results


@router.get("/lineage/{pipeline_id}")
def dbt_lineage(
    pipeline_id: str,
    x_ude_project: Optional[str] = Header(None, alias="X-UDE-Project"),
):
    """
    Get model lineage for a pipeline from manifest.json.
    Returns DAG of model dependencies for operator UI.
    """
    lineage = DbtResults.parse_manifest()

    if not lineage:
        raise HTTPException(
            status_code=404,
            detail="No manifest.json found — run dbt compile first"
        )

    # Filter to nodes related to this pipeline
    pipeline_nodes = {
        node_id: node
        for node_id, node in lineage.items()
        if pipeline_id in node.get("name", "")
    }

    return {
        "pipeline_id": pipeline_id,
        "nodes": pipeline_nodes,
        "total_nodes": len(pipeline_nodes),
    }


@router.get("/artifacts")
def dbt_artifacts():
    """List available dbt artifacts."""
    from pathlib import Path

    artifacts = []
    target_dir = Path("dbt/target")

    if target_dir.exists():
        for f in target_dir.iterdir():
            if f.suffix == ".json":
                artifacts.append({
                    "name": f.name,
                    "size_bytes": f.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        f.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })

    return {"artifacts": artifacts, "total": len(artifacts)}