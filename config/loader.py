# config/loader.py
"""
Pipeline config loader — reads from filesystem AND Bigtable registry.

Source of truth priority:
  1. Bigtable pipeline_config#{id} keys  — set by POST /pipeline/ (API-registered)
  2. config/pipelines/*.yml files        — set by manual file drop or ude pipeline new

This means:
  - 3rd party users who install via pip can register pipelines via the API
    without touching the engine filesystem
  - Existing file-based pipelines continue to work unchanged
  - Bigtable-registered pipelines survive engine restarts (persisted in .state/)

The engine calls load_pipelines() at the top of every cycle so new pipelines
registered via the API are picked up without an engine restart.
"""

import yaml
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PIPELINES_DIR      = Path("config/pipelines")
ENGINE_CONFIG_PATH = Path("config/engine.yml")
PIPELINE_KEY_PREFIX = "pipeline_config#"


def load_pipelines() -> list[dict]:
    """
    Load all pipeline configs from both sources.

    Bigtable-registered pipelines take precedence over filesystem ones
    when the same pipeline_id exists in both. This lets the API update
    a pipeline config without the operator editing YAML files.
    """
    filesystem_pipelines = _load_from_filesystem()
    bigtable_pipelines   = _load_from_bigtable()

    # Merge: Bigtable overrides filesystem for same pipeline_id
    merged: dict[str, dict] = {}

    for p in filesystem_pipelines:
        merged[p["pipeline_id"]] = p

    for p in bigtable_pipelines:
        pid = p["pipeline_id"]
        if pid in merged:
            logger.debug(f"[Loader] Bigtable overrides filesystem config for '{pid}'")
        merged[pid] = p

    result = list(merged.values())
    logger.info(f"[Loader] ------ {len(result)} pipeline(s) loaded "
                f"({len(filesystem_pipelines)} filesystem, {len(bigtable_pipelines)} API-registered)")
    return result


def register_pipeline(config: dict) -> bool:
    """
    Persist a pipeline config to Bigtable so it survives engine restarts
    and is visible to all engine instances without filesystem access.

    Also writes the YAML to config/pipelines/ if the directory exists
    (write-through for local dev convenience).

    Returns True on success.
    """
    pipeline_id = config.get("pipeline_id")
    if not pipeline_id:
        logger.error("[Loader] Cannot register pipeline — pipeline_id missing")
        return False

    from engine.state.bigtable_client import BigtableClient
    client = BigtableClient()
    ok = client.set(f"{PIPELINE_KEY_PREFIX}{pipeline_id}", config)

    if ok:
        logger.info(f"[Loader] Registered pipeline '{pipeline_id}' in Bigtable")
        # Write-through to filesystem for local dev
        _write_to_filesystem(pipeline_id, config)
    else:
        logger.error(f"[Loader] Failed to register pipeline '{pipeline_id}' in Bigtable")

    return ok


def deregister_pipeline(pipeline_id: str) -> bool:
    """
    Remove a pipeline from the Bigtable registry.
    Also deletes the YAML file if it exists.
    """
    from engine.state.bigtable_client import BigtableClient
    client = BigtableClient()
    ok = client.delete(f"{PIPELINE_KEY_PREFIX}{pipeline_id}")

    # Remove filesystem file too
    yaml_path = PIPELINES_DIR / f"{pipeline_id}.yml"
    if yaml_path.exists():
        yaml_path.unlink()
        logger.info(f"[Loader] Deleted {yaml_path}")

    logger.info(f"[Loader] Deregistered pipeline '{pipeline_id}'")
    return ok


def get_pipeline(pipeline_id: str) -> dict | None:
    """Get a single pipeline config by ID — checks both sources."""
    for p in load_pipelines():
        if p["pipeline_id"] == pipeline_id:
            return p
    return None


def load_engine_config() -> dict:
    """Load global engine config from config/engine.yml."""
    if not ENGINE_CONFIG_PATH.exists():
        logger.warning("[Loader] engine.yml not found — using defaults")
        return {}

    with open(ENGINE_CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    logger.info("[Loader] Engine config loaded")
    return config


# ── Private helpers ───────────────────────────────────────────────────────────

def _load_from_filesystem() -> list[dict]:
    """Load pipeline YAMLs from config/pipelines/."""
    if not PIPELINES_DIR.exists():
        return []

    pipelines = []
    for path in sorted(PIPELINES_DIR.glob("*.yml")):
        try:
            with open(path) as f:
                config = yaml.safe_load(f)

            if not _validate(config, path.name):
                continue

            pipelines.append(config)
            logger.info(
                f"[Loader] Loaded pipeline: {config['pipeline_id']} "
                f"(scd_type={config['scd_type']}) [filesystem]"
            )
        except Exception as e:
            logger.error(f"[Loader] Failed to load {path.name}: {e}")

    return pipelines


def _load_from_bigtable() -> list[dict]:
    """Load pipeline configs registered via the API from Bigtable."""
    try:
        from engine.state.bigtable_client import BigtableClient
        client  = BigtableClient()
        all_keys = client.all_keys()
        pipelines = []

        for key in all_keys:
            if not key.startswith(PIPELINE_KEY_PREFIX):
                continue

            config = client.get(key)
            if not config or not isinstance(config, dict):
                continue

            if not _validate(config, key):
                continue

            pipelines.append(config)
            logger.info(
                f"[Loader] Loaded pipeline: {config['pipeline_id']} "
                f"(scd_type={config['scd_type']}) [API-registered]"
            )

        return pipelines

    except Exception as e:
        logger.warning(f"[Loader] Could not load from Bigtable: {e} — filesystem only")
        return []


def _validate(config: dict, source: str) -> bool:
    """Check required fields. Returns True if valid."""
    required = ["pipeline_id", "subscription_id", "natural_key", "scd_type"]
    missing  = [f for f in required if f not in config]
    if missing:
        logger.error(f"[Loader] Skipping {source} — missing fields: {missing}")
        return False
    return True


def _write_to_filesystem(pipeline_id: str, config: dict) -> None:
    """Write-through: persist registered config as YAML for local dev convenience."""
    if not PIPELINES_DIR.exists():
        return
    try:
        import yaml as _yaml
        path = PIPELINES_DIR / f"{pipeline_id}.yml"
        with open(path, "w") as f:
            _yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        logger.debug(f"[Loader] Write-through: {path}")
    except Exception as e:
        logger.warning(f"[Loader] Write-through failed for '{pipeline_id}': {e}")