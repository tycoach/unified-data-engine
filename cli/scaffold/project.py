# cli/scaffold/project.py
"""
ude init — scaffold a full UDE project skeleton.

"""

from __future__ import annotations

from pathlib import Path

from cli.core.errors import ScaffoldError
from cli.scaffold._renderer import render_template, write_file


def scaffold_project(
    target_dir: Path,
    project_name: str,
    env: str,
    gcp_project: str,
) -> None:
    """
    Generate the full UDE project skeleton in target_dir.
    """
    ctx = {
        "project_name": project_name,
        "env":          env,
        "gcp_project":  gcp_project,
        "is_local":     env == "local",
    }

    try:
        _scaffold_config(target_dir, ctx)
        _scaffold_dbt(target_dir, ctx)
        _scaffold_monitoring(target_dir, ctx)
        _scaffold_root_files(target_dir, ctx)
        _scaffold_directories(target_dir)
    except OSError as exc:
        raise ScaffoldError(f"Failed to scaffold project: {exc}") from exc


# ── Section scaffolders ───────────────────────────────────────────────────────

def _scaffold_config(target_dir: Path, ctx: dict) -> None:
    """config/engine.yml + config/pipelines/ directory."""
    config_dir = target_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "pipelines").mkdir(exist_ok=True)

    write_file(
        target_dir / "config" / "engine.yml",
        render_template("engine.yml.j2", ctx),
    )


def _scaffold_dbt(target_dir: Path, ctx: dict) -> None:
    """dbt project skeleton — project.yml, profiles.yml, packages.yml, directory structure."""
    dbt_dir = target_dir / "dbt"

    dirs = [
        dbt_dir / "models" / "staging",
        dbt_dir / "models" / "marts",
        dbt_dir / "snapshots",
        dbt_dir / "tests" / "generic",
        dbt_dir / "tests" / "singular",
        dbt_dir / "macros",
        dbt_dir / "analyses",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # dbt_project.yml
    write_file(
        dbt_dir / "dbt_project.yml",
        _dbt_project_yml(ctx),
    )

    # profiles.yml
    write_file(
        dbt_dir / "profiles.yml",
        _dbt_profiles_yml(ctx),
    )

    # packages.yml
    write_file(
        dbt_dir / "packages.yml",
        _dbt_packages_yml(),
    )

    # Empty _sources.yml starter
    write_file(
        dbt_dir / "models" / "staging" / "_sources.yml",
        _sources_yml_starter(),
    )

    # gitkeep files so empty dirs are tracked
    for d in [dbt_dir / "snapshots", dbt_dir / "macros", dbt_dir / "analyses"]:
        (d / ".gitkeep").touch()


def _scaffold_monitoring(target_dir: Path, ctx: dict) -> None:
    """monitoring/ directory with prometheus config stubs."""
    monitoring_dir = target_dir / "monitoring"
    (monitoring_dir / "prometheus").mkdir(parents=True, exist_ok=True)
    (monitoring_dir / "grafana" / "dashboards").mkdir(parents=True, exist_ok=True)
    (monitoring_dir / "grafana" / "provisioning").mkdir(parents=True, exist_ok=True)

    write_file(
        monitoring_dir / "prometheus" / "prometheus.yml",
        _prometheus_yml(),
    )


def _scaffold_root_files(target_dir: Path, ctx: dict) -> None:
    """docker-compose.yml, Makefile, .env.example, .gitignore."""
    write_file(
        target_dir / "docker-compose.yml",
        render_template("docker-compose.yml.j2", ctx),
    )

    write_file(
        target_dir / ".env.example",
        _env_example(ctx),
    )

    # Only write .gitignore if one doesn't exist
    gitignore_path = target_dir / ".gitignore"
    if not gitignore_path.exists():
        write_file(gitignore_path, _gitignore())


def _scaffold_directories(target_dir: Path) -> None:
    """Create remaining top-level directories with .gitkeep."""
    dirs = [
        target_dir / "engine" / "ingestion",
        target_dir / "engine" / "schema",
        target_dir / "engine" / "staging",
        target_dir / "engine" / "dbt_runner",
        target_dir / "engine" / "state",
        target_dir / "engine" / "metrics",
        target_dir / "api" / "routers",
        target_dir / "ui" / "pages",
        target_dir / "data-generator" / "scenarios",
        target_dir / "scripts",
        target_dir / "terraform",
        target_dir / "tests" / "unit",
        target_dir / "tests" / "integration",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        gitkeep = d / ".gitkeep"
        if not any(d.iterdir()):
            gitkeep.touch()


# ── Inline templates (short configs that don't need .j2 files) ───────────────

def _dbt_project_yml(ctx: dict) -> str:
    name = ctx["project_name"].lower().replace("-", "_").replace(" ", "_")
    return f"""\
name: {name}
version: '2.0.0'
config-version: 2

model-paths: ['models']
snapshot-paths: ['snapshots']
test-paths: ['tests']
macro-paths: ['macros']
analysis-paths: ['analyses']

models:
  {name}:
    staging:
      +materialized: view
      +schema: staging
    marts:
      +materialized: incremental
      +schema: marts

snapshots:
  {name}:
    +target_schema: snapshots
    +strategy: timestamp

vars:
  batch_id: null
  quarantine_schema: quarantine
"""


def _dbt_profiles_yml(ctx: dict) -> str:
    name = ctx["project_name"].lower().replace("-", "_").replace(" ", "_")
    gcp  = ctx["gcp_project"]
    return f"""\
{name}:
  target: "{{{{ env_var('DBT_TARGET', 'dev') }}}}"
  outputs:
    dev:
      type: duckdb
      path: /tmp/{name}_dev.duckdb
      threads: 4

    prod:
      type: bigquery
      method: oauth
      project: {gcp}
      dataset: dbt_prod
      threads: 4
      timeout_seconds: 300
      location: US
"""


def _dbt_packages_yml() -> str:
    return """\
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.0.0", "<2.0.0"]
  - package: calogica/dbt_expectations
    version: [">=0.10.0", "<1.0.0"]
"""


def _sources_yml_starter() -> str:
    return """\
# dbt/models/staging/_sources.yml
# AUTO-GENERATED by schema registry — DO NOT EDIT MANUALLY
# To update: ude schema sync
#
# This file is populated automatically when pipelines are registered
# and the schema registry locks a schema. Run:
#   ude pipeline new     — to register a new pipeline
#   ude schema sync      — to regenerate this file from the registry

version: 1

sources: []
"""


def _prometheus_yml() -> str:
    return """\
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: ude_engine
    static_configs:
      - targets: ['host.docker.internal:8000']

  - job_name: pushgateway
    honor_labels: true
    static_configs:
      - targets: ['pushgateway:9091']
"""


def _env_example(ctx: dict) -> str:
    gcp = ctx["gcp_project"]
    return f"""\
# UDE Environment Configuration
# Copy to .env and fill in values

# Environment: local | staging | production
UDE_ENV=local

# GCP project ID (use minisky-local for local dev)
GCP_PROJECT={gcp}

# MiniSky local GCP emulator
MINISKY_URL=http://localhost:9099

# FastAPI
API_HOST=localhost
API_PORT=8000

# dbt target profile
DBT_TARGET=dev

# Prometheus Pushgateway
PUSHGATEWAY_URL=http://localhost:9091

# Grafana
GRAFANA_ADMIN_PASSWORD=admin
"""


def _gitignore() -> str:
    return """\
# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/
.env
*.egg-info/
dist/
build/

# dbt
dbt/target/
dbt/dbt_packages/
dbt/logs/

# UDE
*.duckdb
.ude/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
"""