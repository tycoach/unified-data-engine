# cli/scaffold/pipeline.py
"""
ude pipeline new — scaffold a new pipeline's files.

"""

from __future__ import annotations

from pathlib import Path

from cli.core.errors import ScaffoldError
from cli.scaffold._renderer import render_template, write_file


def scaffold_pipeline(
    pipeline_id: str,
    natural_key: str,
    scd_type: int,
    subscription_id: str,
    null_threshold: float,
    late_arrival_window: str,
    duplicate_window: str,
    fields: dict[str, dict],
    target_dir: Path | None = None,
) -> None:
    """
    Generate pipeline config and dbt model stubs.

    """
    root = target_dir or Path.cwd()

    ctx = {
        "pipeline_id":          pipeline_id,
        "natural_key":          natural_key,
        "scd_type":             scd_type,
        "subscription_id":      subscription_id,
        "null_threshold":       null_threshold,
        "late_arrival_window":  late_arrival_window,
        "duplicate_window":     duplicate_window,
        "fields":               fields,
        "mart_model":           f"dim_{pipeline_id}",
        "staging_model":        f"{pipeline_id}_staged",
        "snapshot_name":        f"{pipeline_id}_snapshot",
        "has_snapshot":         scd_type == 2,
    }

    try:
        _write_pipeline_yaml(root, ctx)
        _write_staging_model(root, ctx)
        _write_mart_model(root, ctx)
        if scd_type == 2:
            _write_snapshot(root, ctx)
    except OSError as exc:
        raise ScaffoldError(
            f"Failed to scaffold pipeline '{pipeline_id}': {exc}"
        ) from exc


# ── Individual file writers ───────────────────────────────────────────────────

def _write_pipeline_yaml(root: Path, ctx: dict) -> None:
    content = render_template("pipeline.yml.j2", ctx)
    path    = root / "config" / "pipelines" / f"{ctx['pipeline_id']}.yml"
    write_file(path, content, overwrite=False)


def _write_staging_model(root: Path, ctx: dict) -> None:
    content = render_template("staging_model.sql.j2", ctx)
    path    = root / "dbt" / "models" / "staging" / f"{ctx['staging_model']}.sql"
    write_file(path, content, overwrite=False)


def _write_mart_model(root: Path, ctx: dict) -> None:
    template = (
        "incremental_model.sql.j2"   # SCD Type 1
        if ctx["scd_type"] == 1
        else "incremental_model.sql.j2"  # Type 2 marts also use incremental
    )
    content = render_template(template, ctx)
    path    = root / "dbt" / "models" / "marts" / f"{ctx['mart_model']}.sql"
    write_file(path, content, overwrite=False)


def _write_snapshot(root: Path, ctx: dict) -> None:
    content = render_template("snapshot.sql.j2", ctx)
    path    = root / "dbt" / "snapshots" / f"{ctx['snapshot_name']}.sql"
    write_file(path, content, overwrite=False)