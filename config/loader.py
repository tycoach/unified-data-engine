# config/loader.py
"""
Pipeline config loader — reads from filesystem AND Bigtable registry.

Source of truth priority:
  1. Bigtable pipeline_config#{token}#{id} keys  — API-registered, project-scoped
  2. Bigtable pipeline_config#{id} keys          — API-registered, no token (legacy)
  3. config/pipelines/*.yml files                — engine-internal, filesystem

Project scoping:
  - When X-UDE-Project header is sent, only that project's pipelines are returned
  - Filesystem pipelines are NEVER returned to external API callers
  - Engine owner (no token or __engine__ token) sees everything
"""

import yaml
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PIPELINES_DIR       = Path("config/pipelines")
ENGINE_CONFIG_PATH  = Path("config/engine.yml")
PIPELINE_KEY_PREFIX = "pipeline_config#"
ENGINE_OWNER_TOKEN  = "__engine__"


def load_pipelines(project_token: str = "") -> list[dict]:
    """
    Load pipeline configs scoped to a project token.

    Args:
        project_token: If set, returns only pipelines registered under
                       this token. If empty or __engine__, returns all.

    Returns:
        List of pipeline config dicts.
    """
    is_engine_owner = (
        not project_token
        or project_token == ENGINE_OWNER_TOKEN
    )

    if is_engine_owner:
        # Engine owner sees everything
        filesystem_pipelines = _load_from_filesystem()
        bigtable_pipelines   = _load_from_bigtable(project_token="")

        merged: dict[str, dict] = {}
        for p in filesystem_pipelines:
            merged[p["pipeline_id"]] = p
        for p in bigtable_pipelines:
            merged[p["pipeline_id"]] = p

        result = list(merged.values())
    else:
        # 3rd party user — only their project's pipelines
        result = _load_from_bigtable(project_token=project_token)

    logger.info(f"[Loader] ------ {len(result)} pipeline(s) loaded "
                f"(token={'<engine>' if is_engine_owner else project_token[:12]}...)")
    return result


def register_pipeline(config: dict, project_token: str = "") -> bool:
    """
    Persist a pipeline config to Bigtable, namespaced by project token.

    Key format:
      With token:    pipeline_config#{token}#{pipeline_id}
      Without token: pipeline_config#{pipeline_id}
    """
    pipeline_id = config.get("pipeline_id")
    if not pipeline_id:
        logger.error("[Loader] Cannot register pipeline — pipeline_id missing")
        return False

    key = _make_key(pipeline_id, project_token)

    from engine.state.bigtable_client import BigtableClient
    client = BigtableClient()
    ok = client.set(key, config)

    if ok:
        logger.info(f"[Loader] Registered pipeline '{pipeline_id}' "
                    f"(token={project_token[:12] if project_token else 'none'})")
        # Write-through to filesystem only for engine owner (no token)
        if not project_token or project_token == ENGINE_OWNER_TOKEN:
            _write_to_filesystem(pipeline_id, config)
    else:
        logger.error(f"[Loader] Failed to register pipeline '{pipeline_id}'")

    return ok


def deregister_pipeline(pipeline_id: str, project_token: str = "") -> bool:
    """Remove a pipeline from the Bigtable registry."""
    from engine.state.bigtable_client import BigtableClient
    client = BigtableClient()

    key = _make_key(pipeline_id, project_token)
    ok  = client.delete(key)

    # Remove filesystem file only for engine owner
    if not project_token or project_token == ENGINE_OWNER_TOKEN:
        yaml_path = PIPELINES_DIR / f"{pipeline_id}.yml"
        if yaml_path.exists():
            yaml_path.unlink()
            logger.info(f"[Loader] Deleted {yaml_path}")

    logger.info(f"[Loader] Deregistered pipeline '{pipeline_id}'")
    return ok


def get_pipeline(pipeline_id: str, project_token: str = "") -> dict | None:
    """Get a single pipeline config by ID, scoped to project token."""
    for p in load_pipelines(project_token=project_token):
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

def _make_key(pipeline_id: str, project_token: str) -> str:
    """Build the Bigtable key for a pipeline."""
    if project_token and project_token != ENGINE_OWNER_TOKEN:
        return f"{PIPELINE_KEY_PREFIX}{project_token}#{pipeline_id}"
    return f"{PIPELINE_KEY_PREFIX}{pipeline_id}"


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
            config["registered_via"] = "filesystem"
            pipelines.append(config)
            logger.info(
                f"[Loader] Loaded pipeline: {config['pipeline_id']} "
                f"(scd_type={config['scd_type']}) [filesystem]"
            )
        except Exception as e:
            logger.error(f"[Loader] Failed to load {path.name}: {e}")

    return pipelines


def _load_from_bigtable(project_token: str = "") -> list[dict]:
    """
    Load pipeline configs from Bigtable.

    If project_token is set, only loads keys matching:
      pipeline_config#{token}#{id}

    If no token, loads all pipeline_config# keys (engine owner view).
    """
    try:
        from engine.state.bigtable_client import BigtableClient
        client   = BigtableClient()
        all_keys = client.all_keys()
        pipelines = []

        for key in all_keys:
            if not key.startswith(PIPELINE_KEY_PREFIX):
                continue

            # Parse the key structure
            rest = key[len(PIPELINE_KEY_PREFIX):]

            if project_token and project_token != ENGINE_OWNER_TOKEN:
                # Scoped load — only keys matching this token
                expected_prefix = f"{project_token}#"
                if not rest.startswith(expected_prefix):
                    continue
            else:
                # Engine owner — skip tokenised keys (show as separate entries)
                # or include all — here we include all for full visibility
                pass

            config = client.get(key)
            if not config or not isinstance(config, dict):
                continue
            if not _validate(config, key):
                continue

            config["registered_via"] = "api"
            pipelines.append(config)
            logger.info(
                f"[Loader] Loaded pipeline: {config['pipeline_id']} "
                f"(scd_type={config['scd_type']}) [API-registered]"
            )

        return pipelines

    except Exception as e:
        logger.warning(f"[Loader] Could not load from Bigtable: {e}")
        return []


def _validate(config: dict, source: str) -> bool:
    required = ["pipeline_id", "subscription_id", "natural_key", "scd_type"]
    missing  = [f for f in required if f not in config]
    if missing:
        logger.error(f"[Loader] Skipping {source} — missing fields: {missing}")
        return False
    return True


def _write_to_filesystem(pipeline_id: str, config: dict) -> None:
    if not PIPELINES_DIR.exists():
        return
    try:
        path = PIPELINES_DIR / f"{pipeline_id}.yml"
        with open(path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        logger.debug(f"[Loader] Write-through: {path}")
    except Exception as e:
        logger.warning(f"[Loader] Write-through failed for '{pipeline_id}': {e}")