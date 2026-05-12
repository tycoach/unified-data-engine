"""
ude — Unified Data Engine CLI

Entry point registered in pyproject.toml:
    [project.scripts]
    ude = "cli.main:app"

Usage:
    ude --help
    ude up
    ude pipeline list
    ude dbt run
    ude schema sync
    ude quarantine list
    ude observe watch
"""

from __future__ import annotations

import sys
from typing import Optional

import typer
from rich.panel import Panel

from cli.commands import dbt, lifecycle, observe, pipeline, quarantine, schema
from cli.core.config import load_config
from cli.core.context import UDEContext
from cli.core.errors import UDEError
from cli.output.console import console, err_console, print_error

app = typer.Typer(
    name="ude",
    help="Unified Data Engine — GCP-native dbt-powered micro-batch pipeline engine.",
    no_args_is_help=False,       # we handle the no-args case ourselves below
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,  # we handle exceptions ourselves
    add_completion=True,
)

# Register command groups
app.add_typer(lifecycle.app, name="lifecycle", hidden=True)   # top-level aliases added below
app.add_typer(dbt.app,       name="dbt",       help="dbt commands — run, test, snapshot, docs, lineage")
app.add_typer(pipeline.app,  name="pipeline",  help="Pipeline management — list, inspect, new, enable, disable")
app.add_typer(schema.app,    name="schema",    help="Schema operations — sync, history, diff, approve")
app.add_typer(quarantine.app,name="quarantine",help="Quarantine management — list, inspect, approve, reject, replay")
app.add_typer(observe.app,   name="observe",   help="Observability — logs, metrics, watch")


# ── Global options ────────────────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    host: Optional[str] = typer.Option(
        None, "--host", "-H",
        help="UDE API host (overrides UDE_HOST env var and ~/.ude/config.yml)",
        envvar="UDE_HOST",
    ),
    port: Optional[int] = typer.Option(
        None, "--port", "-p",
        help="UDE API port (overrides UDE_PORT env var and ~/.ude/config.yml)",
        envvar="UDE_PORT",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Show detailed output",
    ),
    json_output: bool = typer.Option(
        False, "--json",
        help="Emit machine-readable JSON output",
    ),
) -> None:
    """
    [bold]ude[/bold] — Unified Data Engine CLI

    Manage pipelines, schemas, quarantine, dbt, and observability
    from a single command.

    [muted]Run [bold]ude COMMAND --help[/bold] for help on any command.[/muted]
    """
    cfg = load_config(host=host, port=port)
    ctx.ensure_object(dict)
    ctx.obj = UDEContext(config=cfg, verbose=verbose, output_json=json_output)

    # If no subcommand — show the welcome panel
    if ctx.invoked_subcommand is None:
        _show_welcome(cfg)


# ── Lifecycle aliases at the top level ───────────────────────────────────────
# These let users type `ude up` instead of `ude lifecycle up`

@app.command(name="up", help="Start the UDE stack (engine + API + UI + monitoring)")
def cmd_up(ctx: typer.Context) -> None:
    from cli.commands.lifecycle import up
    up(ctx)


@app.command(name="down", help="Stop the UDE stack")
def cmd_down(ctx: typer.Context) -> None:
    from cli.commands.lifecycle import down
    down(ctx)


@app.command(name="status", help="Show stack health — engine, MiniSky, API, dbt")
def cmd_status(ctx: typer.Context) -> None:
    from cli.commands.lifecycle import status
    status(ctx)


@app.command(name="seed", help="Publish synthetic test data to Pub/Sub")
def cmd_seed(ctx: typer.Context) -> None:
    from cli.commands.lifecycle import seed
    seed(ctx)


@app.command(name="init", help="Scaffold a new UDE project in the current directory")
def cmd_init(ctx: typer.Context) -> None:
    from cli.commands.lifecycle import init
    init(ctx)


# ── Error handler ─────────────────────────────────────────────────────────────

def _run() -> None:
    """
    Wraps app() with a top-level error handler.
    UDEError subclasses render as clean Rich panels.
    Everything else is re-raised (real bugs should still show tracebacks in dev).
    """
    try:
        app()
    except UDEError as exc:
        err_console.print(
            Panel(
                str(exc),
                title="[error]Error[/error]",
                border_style="red",
                padding=(0, 1),
            )
        )
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        console.print("\n[muted]Interrupted.[/muted]")
        sys.exit(0)


def _show_welcome(cfg) -> None:
    from cli.core.checks import stack_is_running, minisky_is_alive
    from cli.output.console import console
    from rich.table import Table

    stack_up = stack_is_running(cfg)
    minisky_up = minisky_is_alive(cfg)

    status_table = Table.grid(padding=(0, 2))
    status_table.add_column(style="muted")
    status_table.add_column()

    status_table.add_row(
        "API stack",
        "[success]running[/success]" if stack_up else "[error]not running[/error]",
    )
    status_table.add_row(
        "MiniSky",
        "[success]running[/success]" if minisky_up else "[warning]not running[/warning]",
    )
    status_table.add_row("Environment", f"[info]{cfg.env}[/info]")
    status_table.add_row("API", f"[muted]{cfg.api_base_url}[/muted]")

    console.print()
    console.print(Panel(
        status_table,
        title="[bold]ude — Unified Data Engine[/bold]",
        subtitle="[muted]Run [bold]ude --help[/bold] for available commands[/muted]",
        border_style="cyan",
        padding=(1, 2),
    ))

    if not stack_up:
        console.print()
        console.print("  [muted]Start the stack with:[/muted] [bold]ude up[/bold]")

    console.print()


if __name__ == "__main__":
    _run()