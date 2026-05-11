# config/loader.py
# Reads pipeline configs from config/pipelines/*.yml
# Adding a new pipeline = drop a YAML file, no code changes needed
#
# Usage:
#   from config.loader import load_pipelines, load_engine_config
#   pipelines = load_pipelines()

import yaml
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PIPELINES_DIR = Path("config/pipelines")
ENGINE_CONFIG_PATH = Path("config/engine.yml")


def load_pipelines() -> list[dict]:
    """
    Load all pipeline configs from config/pipelines/*.yml.
    Returns list of pipeline config dicts.
    Each dict is passed directly to EdgeCaseHandler and MicroBatchConsumer.
    """
    if not PIPELINES_DIR.exists():
        logger.warning(f"[Loader] Pipelines dir not found: {PIPELINES_DIR}")
        return []

    pipelines = []
    for path in sorted(PIPELINES_DIR.glob("*.yml")):
        try:
            with open(path) as f:
                config = yaml.safe_load(f)

            # Validate required fields
            required = ["pipeline_id", "subscription_id", "natural_key", "scd_type"]
            missing = [f for f in required if f not in config]
            if missing:
                logger.error(
                    f"[Loader] Skipping {path.name} — missing fields: {missing}"
                )
                continue

            pipelines.append(config)
            logger.info(
                f"[Loader] Loaded pipeline: {config['pipeline_id']} "
                f"(scd_type={config['scd_type']})"
            )

        except Exception as e:
            logger.error(f"[Loader] Failed to load {path.name}: {e}")

    logger.info(f"[Loader] ------ {len(pipelines)} pipeline(s) loaded")
    return pipelines


def load_engine_config() -> dict:
    """Load global engine config from config/engine.yml."""
    if not ENGINE_CONFIG_PATH.exists():
        logger.warning("[Loader] engine.yml not found — using defaults")
        return {}

    with open(ENGINE_CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    logger.info("[Loader] Engine config loaded")
    return config


def get_pipeline(pipeline_id: str) -> dict | None:
    """Get a single pipeline config by ID."""
    for p in load_pipelines():
        if p["pipeline_id"] == pipeline_id:
            return p
    return None