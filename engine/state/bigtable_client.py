# engine/state/bigtable_client.py
# Hot state store — replaces RocksDB from UDE v1
# Stores: schema versions, batch offsets, active dimension cache, checkpoints
#
# Local dev: JSON files under .state/ (fast, no dependency)
# Production: swap _get/_set for real Bigtable client calls
#
# Access pattern: sub-millisecond reads, key-value only
# Think of this as the engine's RAM with a disk backup

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# State directory — absolute path so it works regardless of cwd
# This ensures the pipx-installed API and the engine repo both
# read from the same location
STATE_DIR = Path.home() / ".ude" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


class BigtableClient:
    """
    Hot state store for the UDE engine.
    
    Key namespaces:
      schema#{pipeline_id}        → current locked schema version
      offset#{pipeline_id}        → last committed batch offset
      checkpoint#{batch_id}       → batch processing state
      dim_cache#{pipeline_id}#{key} → active dimension record cache
    
    Local dev uses JSON files under .state/
    Production: replace _get/_set with google.cloud.bigtable calls
    """

    def __init__(self, instance_id: str = "ude-state"):
        STATE_DIR.mkdir(exist_ok=True)
        self.instance_id = instance_id
        logger.info(
            f"[Bigtable] Initialized | instance={instance_id} | "
            f"state_dir={STATE_DIR.resolve()}"
        )

    def _path(self, key: str) -> Path:
        # Replace # with -- for safe filenames
        safe_key = key.replace("#", "--").replace("/", "_")
        return STATE_DIR / f"{safe_key}.json"

    def set(self, key: str, value: dict) -> bool:
        """Write a value to hot state. Returns True on success."""
        try:
            data = {
                "key": key,
                "value": value,
                "written_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(self._path(key), "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"[Bigtable] SET {key}")
            return True
        except Exception as e:
            logger.error(f"[Bigtable] SET failed for {key}: {e}")
            return False

    def get(self, key: str) -> dict | None:
        """Read a value from hot state. Returns None if not found."""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return data.get("value")
        except Exception as e:
            logger.error(f"[Bigtable] GET failed for {key}: {e}")
            return None

    def delete(self, key: str) -> bool:
        """Delete a key from hot state."""
        path = self._path(key)
        if path.exists():
            path.unlink()
            logger.debug(f"[Bigtable] DELETE {key}")
            return True
        return False

    def exists(self, key: str) -> bool:
        """Check if a key exists in hot state."""
        return self._path(key).exists()

    # ── Schema version state ──────────────────────────────────────────────────

    def set_schema_version(self, pipeline_id: str, version: int):
        """Cache current schema version for sub-millisecond deviation checks."""
        self.set(f"schema#{pipeline_id}", {"version": version})
        logger.info(
            f"[Bigtable] Schema version cached: "
            f"{pipeline_id} → v{version}"
        )

    def get_schema_version(self, pipeline_id: str) -> int | None:
        """Get cached schema version. None = schema not yet locked."""
        data = self.get(f"schema#{pipeline_id}")
        return data["version"] if data else None

    # ── Batch offset state ────────────────────────────────────────────────────

    def set_last_committed_batch(self, pipeline_id: str, batch_id: str):
        """Record last successfully committed batch for this pipeline."""
        self.set(
            f"offset#{pipeline_id}",
            {
                "batch_id": batch_id,
                "committed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info(
            f"[Bigtable] Committed offset: {pipeline_id} → {batch_id}"
        )

    def get_last_committed_batch(self, pipeline_id: str) -> dict | None:
        """Get last committed batch info."""
        return self.get(f"offset#{pipeline_id}")

    # ── Checkpoint state ──────────────────────────────────────────────────────

    def write_checkpoint(self, batch_id: str, state: dict) -> bool:
        """Write full batch checkpoint after dbt tests pass."""
        ok = self.set(f"checkpoint#{batch_id}", state)
        if ok:
            logger.info(f"[Bigtable] Checkpoint written: {batch_id}")
        return ok

    def get_checkpoint(self, batch_id: str) -> dict | None:
        """Retrieve checkpoint for a batch."""
        return self.get(f"checkpoint#{batch_id}")

    # ── Dimension cache ───────────────────────────────────────────────────────

    def cache_dim_record(self, pipeline_id: str, natural_key: str, record: dict):
        """Cache an active dimension record for fast MERGE lookups."""
        self.set(f"dim_cache#{pipeline_id}#{natural_key}", record)

    def get_dim_record(self, pipeline_id: str, natural_key: str) -> dict | None:
        """Retrieve a cached dimension record."""
        return self.get(f"dim_cache#{pipeline_id}#{natural_key}")

    def all_keys(self) -> list[str]:
        """List all keys in hot state — used by health endpoint."""
        keys = []
        for path in STATE_DIR.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                keys.append(data.get("key", path.stem))
            except Exception:
                pass
        return keys