# cli/commands/lifecycle.py
"""
Lifecycle commands — ude up / down / status / seed / init

ude init now generates a project token and saves it to ~/.ude/config.yml.
The token scopes all subsequent API calls to the user's pipelines only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
import click
from rich.panel import Panel
from rich.table import Table

from cli.core.checks import (
    assert_minisky_alive,
    assert_project_exists,
    minisky_is_alive,
    stack_is_running,
)
from cli.core.context import UDEContext
from cli.core.errors import NoProjectError
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Stack lifecycle — up, down, status, seed, init")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude up ────────────────────────────────────────────────────────────────────

@app.command()
def up(ctx: typer.Context) -> None:
    """Start the UDE stack — engine, API, UI, and monitoring."""
    ude_ctx = _ctx(ctx)
    assert_project_exists()

    print_info("Checking MiniSky...")
    if not minisky_is_alive(ude_ctx.config):
        print_warning("MiniSky not detected. Attempting to start...")
        _run_shell("minisky start", "MiniSky")

    print_info("Starting UDE stack via make up...")
    _run_shell("make up", "Stack")
    print_success("Stack is up.")
    print_info(f"API    → {ude_ctx.config.api_base_url}/docs")
    print_info("UI     → http://localhost:8501")
    print_info("Grafana → http://localhost:3000  (admin / admin)")


# ── ude down ──────────────────────────────────────────────────────────────────

@app.command()
def down(ctx: typer.Context) -> None:
    """Stop the UDE stack."""
    assert_project_exists()
    print_info("Stopping UDE stack via make down...")
    _run_shell("make down", "Stack")
    print_success("Stack stopped.")


# ── ude status ────────────────────────────────────────────────────────────────

@app.command()
def status(ctx: typer.Context) -> None:
    """Show health of every component — API, MiniSky, dbt, monitoring."""
    ude_ctx = _ctx(ctx)
    cfg = ude_ctx.config

    import shutil
    rows = [
        ("API stack",  stack_is_running(cfg),         f"{cfg.api_base_url}/health"),
        ("MiniSky",    minisky_is_alive(cfg),          cfg.minisky_url),
        ("dbt",        shutil.which("dbt") is not None, "on PATH"),
        ("Prometheus", _port_open(9090),               "http://localhost:9090"),
        ("Grafana",    _port_open(3000),               "http://localhost:3000"),
        ("Streamlit",  _port_open(8501),               "http://localhost:8501"),
    ]

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Component", style="label")
    table.add_column("Status")
    table.add_column("Address", style="muted")

    for name, alive, addr in rows:
        status_str = (
            "[success]● running[/success]"
            if alive
            else "[error]○ not running[/error]"
        )
        table.add_row(name, status_str, addr)

    # Project info row
    project_str = (
        f"[info]{cfg.project_name}[/info] [muted]({cfg.project_token})[/muted]"
        if cfg.has_project
        else "[warning]No project — run ude init[/warning]"
    )

    console.print()
    console.print(Panel(
        table,
        title=f"[bold]UDE Status[/bold] · env=[info]{cfg.env}[/info] · project={project_str}",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


# ── ude seed ──────────────────────────────────────────────────────────────────

@app.command()
def seed(
    ctx: typer.Context,
    scenario: Optional[str] = typer.Option(
        None, "--scenario", "-s",
        help="Scenario to seed (e.g. happy_path, products). Defaults to all."
    ),
) -> None:
    """Publish synthetic test data to Pub/Sub."""
    assert_project_exists()
    assert_minisky_alive(_ctx(ctx).config)

    cmd = "make seed"
    if scenario:
        cmd = f"python data-generator/scenarios/{scenario}.py"

    print_info(f"Seeding data ({scenario or 'all scenarios'})...")
    _run_shell(cmd, "Seed")
    print_success("Data published to Pub/Sub.")


# ── ude init ──────────────────────────────────────────────────────────────────

@app.command()
def init(ctx: typer.Context) -> None:
    """
    Scaffold a new UDE project and generate a project token.

    The project token scopes all your pipelines — only your pipelines
    are visible when you run ude pipeline list. Engine-internal pipelines
    are never shown to external users.
    """
    from cli.scaffold.project import scaffold_project
    from cli.core.config import generate_token, write_config, config_exists, load_config

    cwd = Path.cwd()

    if (cwd / "config" / "engine.yml").exists():
        overwrite = typer.confirm(
            "A UDE project already exists here. Reinitialise?",
            default=False,
        )
        if not overwrite:
            print_info("Aborted.")
            raise typer.Exit()

    console.print()
    console.print("[bold]UDE Project Setup[/bold]")
    console.print("[muted]Answer a few questions to scaffold your project.[/muted]")
    console.print()

    project_name = typer.prompt("Project name", default=cwd.name)
    env          = typer.prompt(
        "Environment", default="local",
        type=click.Choice(["local", "staging", "production"])
    )
    gcp_project  = typer.prompt(
        "GCP project ID (leave blank for MiniSky local dev)", default=""
    )

    # Generate project token
    token = generate_token(project_name)

    scaffold_project(
        target_dir=cwd,
        project_name=project_name,
        env=env,
        gcp_project=gcp_project or "minisky-local",
    )

    # Save token to ~/.ude/config.yml
    existing_cfg = {}
    if config_exists():
        from cli.core.config import _load_file
        existing_cfg = _load_file()

    existing_cfg.update({
        "host":          existing_cfg.get("host", "localhost"),
        "port":          existing_cfg.get("port", 8000),
        "env":           env,
        "minisky_url":   existing_cfg.get("minisky_url", "http://localhost:8080"),
        "timeout":       existing_cfg.get("timeout", 30),
        "project_token": token,
        "project_name":  project_name,
    })
    write_config(existing_cfg)

    console.print()
    print_success(f"Project '[bold]{project_name}[/bold]' created.")
    console.print()
    console.print(Panel(
        f"[bold]Project token:[/bold] [info]{token}[/info]\n\n"
        f"[muted]Saved to ~/.ude/config.yml\n"
        f"Share this token with teammates who need access to the same project.\n"
        f"Set via env var: [bold]UDE_PROJECT_TOKEN={token}[/bold][/muted]",
        title="[bold]Project Identity[/bold]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()
    print_info("Next steps:")
    console.print("  1. [bold]minisky start[/bold]         — start local GCP emulator")
    console.print("  2. [bold]make provision[/bold]        — create Pub/Sub topics")
    console.print("  3. [bold]ude up[/bold]                — start the full stack")
    console.print("  4. [bold]ude pipeline new[/bold]      — register your first pipeline")
    console.print()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_shell(cmd: str, label: str) -> None:
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print_error(f"{label} command failed (exit {result.returncode})")
        raise typer.Exit(code=result.returncode)


def _port_open(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("localhost", port)) == 0