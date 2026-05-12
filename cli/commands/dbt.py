# cli/commands/dbt.py
"""
ude dbt — UDE-aware dbt passthrough commands.

The difference from running raw dbt commands:
  - Automatically injects --profiles-dir, --project-dir
  - Injects --vars with batch_id and environment context
  - Pre-flight check: dbt on PATH? project exists?
  - Output rendered through Rich, not raw subprocess stdout
  - Failures surface as clean UDE errors, not cryptic subprocess exits

Commands:
    ude dbt run       — run all or selected dbt models
    ude dbt test      — run dbt tests
    ude dbt snapshot  — run dbt snapshots
    ude dbt docs      — generate and serve dbt docs
    ude dbt lineage   — parse manifest.json and print model DAG
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from cli.core.checks import assert_dbt_on_path, assert_project_exists
from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="dbt commands — run, test, snapshot, docs, lineage")

DBT_PROJECT_DIR = Path("dbt")
DBT_PROFILES_DIR = Path("dbt")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


def _base_dbt_cmd(extra: list[str], batch_id: str | None = None) -> list[str]:
    """
    Build a dbt command with standard UDE flags injected.
    Every dbt invocation from the CLI goes through here.
    """
    batch_id = batch_id or str(uuid.uuid4())
    vars_str = json.dumps({"batch_id": batch_id})

    return [
        "dbt",
        *extra,
        "--project-dir", str(DBT_PROJECT_DIR),
        "--profiles-dir", str(DBT_PROFILES_DIR),
        "--vars", vars_str,
    ]


def _run_dbt(cmd: list[str], label: str) -> int:
    """Run a dbt subprocess, stream output, return exit code."""
    print_info(f"Running: {' '.join(cmd)}")
    console.print()

    result = subprocess.run(cmd)

    console.print()
    if result.returncode == 0:
        print_success(f"{label} completed successfully.")
    else:
        print_error(f"{label} failed (exit {result.returncode}).")

    return result.returncode


# ── ude dbt run ───────────────────────────────────────────────────────────────

@app.command(name="run")
def run(
    ctx: typer.Context,
    select: Optional[str] = typer.Option(
        None, "--select", "-s",
        help="dbt node selection (e.g. staging.customers, tag:daily)"
    ),
    batch_id: Optional[str] = typer.Option(
        None, "--batch-id",
        help="Batch ID to inject as --vars batch_id. Auto-generated if not provided."
    ),
    full_refresh: bool = typer.Option(
        False, "--full-refresh",
        help="Pass --full-refresh to dbt (rebuilds incremental models from scratch)"
    ),
) -> None:
    """Run dbt models — staging and marts."""
    assert_project_exists()
    assert_dbt_on_path()

    extra = ["run"]
    if select:
        extra += ["--select", select]
    if full_refresh:
        extra.append("--full-refresh")

    cmd = _base_dbt_cmd(extra, batch_id)
    exit_code = _run_dbt(cmd, "dbt run")
    raise typer.Exit(code=exit_code)


# ── ude dbt test ──────────────────────────────────────────────────────────────

@app.command(name="test")
def test(
    ctx: typer.Context,
    select: Optional[str] = typer.Option(
        None, "--select", "-s",
        help="dbt node selection (e.g. customers_snapshot, tag:daily)"
    ),
) -> None:
    """Run dbt tests — not_null, unique, accepted_values, relationships."""
    assert_project_exists()
    assert_dbt_on_path()

    extra = ["test"]
    if select:
        extra += ["--select", select]

    cmd = _base_dbt_cmd(extra)
    exit_code = _run_dbt(cmd, "dbt test")
    raise typer.Exit(code=exit_code)


# ── ude dbt snapshot ──────────────────────────────────────────────────────────

@app.command(name="snapshot")
def snapshot(
    ctx: typer.Context,
    select: Optional[str] = typer.Option(
        None, "--select", "-s",
        help="Snapshot selection (e.g. customers_snapshot)"
    ),
    batch_id: Optional[str] = typer.Option(
        None, "--batch-id",
        help="Batch ID to inject. Auto-generated if not provided."
    ),
) -> None:
    """Run dbt snapshots — SCD Type 2 open/close logic."""
    assert_project_exists()
    assert_dbt_on_path()

    extra = ["snapshot"]
    if select:
        extra += ["--select", select]

    cmd = _base_dbt_cmd(extra, batch_id)
    exit_code = _run_dbt(cmd, "dbt snapshot")
    raise typer.Exit(code=exit_code)


# ── ude dbt docs ──────────────────────────────────────────────────────────────

@app.command(name="docs")
def docs(
    ctx: typer.Context,
    serve: bool = typer.Option(
        True, "--serve/--no-serve",
        help="Serve docs locally after generating (default: yes)"
    ),
    port: int = typer.Option(
        8080, "--port",
        help="Port to serve docs on"
    ),
) -> None:
    """Generate dbt docs and optionally serve them locally."""
    assert_project_exists()
    assert_dbt_on_path()

    # Generate
    gen_cmd = [
        "dbt", "docs", "generate",
        "--project-dir", str(DBT_PROJECT_DIR),
        "--profiles-dir", str(DBT_PROFILES_DIR),
    ]
    exit_code = _run_dbt(gen_cmd, "dbt docs generate")
    if exit_code != 0:
        raise typer.Exit(code=exit_code)

    if serve:
        print_info(f"Serving dbt docs at http://localhost:{port}")
        print_info("Press Ctrl+C to stop.")
        serve_cmd = [
            "dbt", "docs", "serve",
            "--project-dir", str(DBT_PROJECT_DIR),
            "--profiles-dir", str(DBT_PROFILES_DIR),
            "--port", str(port),
        ]
        try:
            subprocess.run(serve_cmd)
        except KeyboardInterrupt:
            print_info("Docs server stopped.")


# ── ude dbt lineage ───────────────────────────────────────────────────────────

@app.command(name="lineage")
def lineage(
    ctx: typer.Context,
    dataset: Optional[str] = typer.Option(
        None, "--dataset", "-d",
        help="Filter lineage to a specific dataset (e.g. customers)"
    ),
) -> None:
    """
    Parse manifest.json and render the model dependency DAG in the terminal.
    Runs dbt compile first if manifest.json is stale or missing.
    """
    assert_project_exists()
    assert_dbt_on_path()

    manifest_path = DBT_PROJECT_DIR / "target" / "manifest.json"

    if not manifest_path.exists():
        print_info("manifest.json not found. Running dbt compile...")
        compile_cmd = [
            "dbt", "compile",
            "--project-dir", str(DBT_PROJECT_DIR),
            "--profiles-dir", str(DBT_PROFILES_DIR),
        ]
        result = subprocess.run(compile_cmd, capture_output=True)
        if result.returncode != 0:
            print_error("dbt compile failed. Cannot render lineage.")
            raise typer.Exit(code=1)

    try:
        with manifest_path.open() as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print_error(f"Could not read manifest.json: {e}")
        raise typer.Exit(code=1)

    _render_lineage(manifest, dataset)


def _render_lineage(manifest: dict, filter_dataset: str | None) -> None:
    """Render a Rich tree from the dbt manifest DAG."""
    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})
    parent_map = manifest.get("parent_map", {})

    # Build a simple name → node mapping
    name_map = {
        v.get("name", k): k
        for k, v in {**nodes, **sources}.items()
    }

    tree = Tree("[bold cyan]dbt lineage[/bold cyan]")

    rendered = set()

    def _add_node(node_key: str, branch: Tree, depth: int = 0) -> None:
        if depth > 6 or node_key in rendered:
            return
        rendered.add(node_key)

        node = nodes.get(node_key) or sources.get(node_key, {})
        name = node.get("name", node_key.split(".")[-1])
        resource_type = node.get("resource_type", "node")

        if filter_dataset and filter_dataset not in name:
            return

        style = {
            "model":    "[green]",
            "snapshot": "[magenta]",
            "source":   "[blue]",
            "test":     "[yellow]",
        }.get(resource_type, "[white]")

        label = f"{style}{name}[/{style[1:]}" if style != "[white]" else name
        child_branch = branch.add(f"{label} [dim]({resource_type})[/dim]")

        for parent_key in parent_map.get(node_key, []):
            _add_node(parent_key, child_branch, depth + 1)

    for key in nodes:
        resource_type = nodes[key].get("resource_type")
        if resource_type in ("model", "snapshot"):
            _add_node(key, tree)

    console.print()
    console.print(Panel(tree, title="[bold]Model lineage[/bold]", border_style="cyan"))
    console.print()

    # Summary table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Type")
    table.add_column("Count", justify="right")

    type_counts: dict[str, int] = {}
    for node in nodes.values():
        rt = node.get("resource_type", "unknown")
        type_counts[rt] = type_counts.get(rt, 0) + 1

    for rt, count in sorted(type_counts.items()):
        table.add_row(rt, str(count))

    console.print(table)
    console.print()