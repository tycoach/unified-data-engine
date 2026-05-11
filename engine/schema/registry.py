# engine/schema/registry.py
# Schema registry — locks schema on first load, versions it, persists it
# Local dev: JSON files under .schema_registry/ (fast, no DB dependency)
# Production: swap _load/_save for Cloud SQL queries

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REGISTRY_DIR = Path(".schema_registry")


class SchemaRegistry:
    """
    Stores and retrieves locked schemas per pipeline.
    """

    def __init__(self):
        REGISTRY_DIR.mkdir(exist_ok=True)
        logger.info(f"[Registry] Initialized at {REGISTRY_DIR.resolve()}")

    def _path(self, pipeline_id: str) -> Path:
        return REGISTRY_DIR / f"{pipeline_id}.json"

    def _load(self, pipeline_id: str) -> dict | None:
        path = self._path(pipeline_id)
        if not path.exists():
            return None
        with open(path, "r") as f:
            return json.load(f)

    def _save(self, pipeline_id: str, schema: dict):
        with open(self._path(pipeline_id), "w") as f:
            json.dump(schema, f, indent=2)

    def is_locked(self, pipeline_id: str) -> bool:
        """Returns True if a schema is already locked for this pipeline."""
        return self._path(pipeline_id).exists()

    def lock(self, schema: dict) -> dict:
        """
        Lock a freshly inferred schema .
        Called only on first batch for a pipeline.
        """
        pipeline_id = schema["pipeline_id"]

        if self.is_locked(pipeline_id):
            logger.warning(
                f"[Registry] Schema for '{pipeline_id}' already locked. "
                f"Use evolve() to update."
            )
            return self._load(pipeline_id)

        schema["version"] = 1
        schema["locked_at"] = datetime.now(timezone.utc).isoformat()
        schema["status"] = "LOCKED"

        self._save(pipeline_id, schema)
        logger.info(
            f"[Registry] Locked schema for '{pipeline_id}'  "
            f"fields: {list(schema['fields'].keys())}"
        )
        return schema

    def get_locked(self, pipeline_id: str) -> dict | None:
        """
        Retrieve the currently locked schema for a pipeline.
        Returns None if no schema locked yet (first batch).
        """
        schema = self._load(pipeline_id)
        if schema:
            logger.debug(
                f"[Registry] Loaded schema for '{pipeline_id}' "
                f"v{schema['version']}"
            )
        return schema

    def evolve(self, pipeline_id: str, updated_fields: dict, reason: str) -> dict:
        """
        Evolve schema to next version after an EVOLVED deviation.
        """
        current = self._load(pipeline_id)
        if not current:
            raise ValueError(
                f"[Registry] Cannot evolve — no locked schema for '{pipeline_id}'"
            )

        old_version = current["version"]
        current["fields"] = updated_fields
        current["version"] = old_version + 1
        current["evolved_at"] = datetime.now(timezone.utc).isoformat()
        current["evolution_reason"] = reason
        current["status"] = "LOCKED"

        self._save(pipeline_id, current)
        logger.info(
            f"[Registry] Evolved '{pipeline_id}' "
            f"v{old_version} → v{current['version']} | {reason}"
        )
        return current

    def all_schemas(self) -> list[dict]:
        """Return all locked schemas — used by API /schema endpoint."""
        schemas = []
        for path in REGISTRY_DIR.glob("*.json"):
            with open(path) as f:
                schemas.append(json.load(f))
        return schemas

    def delete(self, pipeline_id: str):
        """Delete a locked schema — forces re-inference on next batch."""
        path = self._path(pipeline_id)
        if path.exists():
            path.unlink()
            logger.info(f"[Registry] Deleted schema for '{pipeline_id}'")