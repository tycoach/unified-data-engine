# cli/commands/observe.py
"""
ude observe — live terminal observability.

Commands:
    ude observe logs     — stream engine logs to the terminal
    ude observe metrics  — snapshot current Prometheus metrics as a table
    ude observe watch    — live dashboard: batch cycles, test results, record counts
"""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from cli.core.checks import assert_stack_running
from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Observability — logs, metrics, watch")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude observe logs ──────────────────────────────────────────────────────────

@app.command(name="logs")
def logs(
    ctx: typer.Context,
    pipeline_id: Optional[str] = typer.Option(
        None, "--pipeline", "-p",
        help="Filter logs to a specific pipeline"
    ),
    level: str = typer.Option(
        "INFO", "--level", "-l",
        help="Minimum log level to show",
        show_choices=True,
    ),
    follow: bool = typer.Option(
        True, "--follow/--no-follow", "-f",
        help="Stream logs live (default: yes)"
    ),
    lines: int = typer.Option(
        50, "--lines", "-n",
        help="Number of historical lines to show before streaming"
    ),
) -> None:
    """
    Stream engine logs to the terminal.

    Log lines are colour-coded by level:
      INFO → cyan · WARNING → yellow · ERROR → red · DEBUG → dim
    """
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.observe import ObserveClient
    client = ObserveClient(ude_ctx.config)

    level_style = {
        "DEBUG":   "dim",
        "INFO":    "cyan",
        "WARNING": "yellow",
        "ERROR":   "bold red",
        "CRITICAL":"bold red on white",
    }

    print_info(
        f"Streaming logs"
        + (f" · pipeline={pipeline_id}" if pipeline_id else "")
        + f" · level≥{level}"
        + (" · Ctrl+C to stop" if follow else "")
    )
    console.print()

    try:
        for entry in client.stream_logs(
            pipeline_id=pipeline_id,
            level=level,
            follow=follow,
            lines=lines,
        ):
            ts        = entry.get("timestamp", "")
            log_level = entry.get("level", "INFO")
            pid       = entry.get("pipeline_id", "")
            message   = entry.get("message", "")
            style     = level_style.get(log_level, "white")

            pid_tag = f"[pipeline] {pid}[/pipeline]" if pid else ""
            console.print(
                f"[muted]{ts}[/muted] [{style}]{log_level:8}[/{style}]"
                f"{pid_tag} {message}"
            )

    except KeyboardInterrupt:
        console.print("\n[muted]Log stream stopped.[/muted]")


# ── ude observe metrics ───────────────────────────────────────────────────────

@app.command(name="metrics")
def metrics(
    ctx: typer.Context,
    pipeline_id: Optional[str] = typer.Option(
        None, "--pipeline", "-p",
        help="Filter metrics to a specific pipeline"
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w",
        help="Refresh every 5 seconds until Ctrl+C"
    ),
) -> None:
    """Snapshot current Prometheus metrics as a readable table."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.observe import ObserveClient
    client = ObserveClient(ude_ctx.config)

    def _render(data: dict) -> Panel:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Metric",    style="muted",    min_width=40)
        table.add_column("Pipeline",  style="pipeline", min_width=14)
        table.add_column("Value",     justify="right")
        table.add_column("Labels",    style="dim")

        for m in data.get("metrics", []):
            table.add_row(
                m.get("name", "—"),
                m.get("pipeline", "—"),
                str(m.get("value", "—")),
                m.get("labels", ""),
            )

        return Panel(
            table,
            title="[bold]UDE Metrics[/bold]"
            + (f" · [pipeline]{pipeline_id}[/pipeline]" if pipeline_id else "")
            + f" [muted]{data.get('scraped_at', '')}[/muted]",
            border_style="cyan",
            padding=(1, 2),
        )

    if not watch:
        data = client.get_metrics(pipeline_id=pipeline_id)
        console.print()
        console.print(_render(data))
        console.print()
        return

    # Watch mode — refresh every 5 seconds
    print_info("Refreshing every 5s · Ctrl+C to stop")
    try:
        with Live(console=console, refresh_per_second=0.2, screen=False) as live:
            while True:
                data = client.get_metrics(pipeline_id=pipeline_id)
                live.update(_render(data))
                time.sleep(5)
    except KeyboardInterrupt:
        console.print("\n[muted]Stopped.[/muted]")


# ── ude observe watch ─────────────────────────────────────────────────────────

@app.command(name="watch")
def watch(
    ctx: typer.Context,
    pipeline_id: Optional[str] = typer.Option(
        None, "--pipeline", "-p",
        help="Watch a specific pipeline only"
    ),
    interval: int = typer.Option(
        5, "--interval", "-i",
        help="Refresh interval in seconds (default: 5)"
    ),
) -> None:
    """
    Live batch feed — shows each cycle's record counts, dbt test results,
    schema status, and quarantine rate as they happen.

    This is the terminal equivalent of the Streamlit operator dashboard.
    Press Ctrl+C to exit.
    """
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.observe import ObserveClient
    client = ObserveClient(ude_ctx.config)

    print_info(
        "Live batch watch"
        + (f" · pipeline={pipeline_id}" if pipeline_id else " · all pipelines")
        + f" · refreshing every {interval}s · Ctrl+C to stop"
    )
    console.print()

    batch_history: list[dict] = []

    def _build_display() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header",  size=3),
            Layout(name="batches", minimum_size=8),
            Layout(name="footer",  size=3),
        )

        # Header
        layout["header"].update(Panel(
            f"[bold]UDE Watch[/bold]  "
            + (f"[pipeline]{pipeline_id}[/pipeline]" if pipeline_id else "[muted]all pipelines[/muted]")
            + f"  [muted]updated {time.strftime('%H:%M:%S')}[/muted]",
            border_style="cyan",
        ))

        # Batch history table
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Time",          style="muted", min_width=10)
        table.add_column("Pipeline",      style="pipeline")
        table.add_column("Records",       justify="right")
        table.add_column("Quarantined",   justify="right")
        table.add_column("dbt",           justify="center")
        table.add_column("Snaps opened",  justify="right")
        table.add_column("Schema")
        table.add_column("Duration",      justify="right", style="muted")

        for b in batch_history[-20:]:  # show last 20 batches
            dbt_status = (
                "[success]✓[/success]" if b.get("dbt_passed")
                else "[error]✗[/error]"
            )
            schema_status = {
                "MATCH":   "[success]MATCH[/success]",
                "EVOLVED": "[warning]EVOLVED[/warning]",
                "BROKEN":  "[error]BROKEN[/error]",
            }.get(b.get("schema_status", "MATCH"), "—")

            qrate = b.get("quarantine_rate", 0)
            q_str = (
                f"[error]{qrate:.1%}[/error]" if qrate > 0.1
                else f"[warning]{qrate:.1%}[/warning]" if qrate > 0
                else "[success]0%[/success]"
            )

            table.add_row(
                b.get("batch_time", "—"),
                b.get("pipeline_id", "—"),
                str(b.get("records_clean", "—")),
                q_str,
                dbt_status,
                str(b.get("snapshot_opened", "—")),
                schema_status,
                f"{b.get('duration_ms', 0):,}ms",
            )

        layout["batches"].update(Panel(
            table,
            title="[bold]Batch cycles[/bold]",
            border_style="dim",
            padding=(0, 1),
        ))

        # Footer — summary stats
        total_records = sum(b.get("records_clean", 0) for b in batch_history)
        total_quarantined = sum(b.get("records_quarantined", 0) for b in batch_history)
        dbt_failures = sum(1 for b in batch_history if not b.get("dbt_passed", True))

        footer_grid = Table.grid(padding=(0, 4))
        footer_grid.add_column()
        footer_grid.add_column()
        footer_grid.add_column()
        footer_grid.add_row(
            f"[muted]Total records:[/muted] [bold]{total_records:,}[/bold]",
            f"[muted]Quarantined:[/muted] [bold]{total_quarantined:,}[/bold]",
            f"[muted]dbt failures:[/muted] "
            + (f"[error]{dbt_failures}[/error]" if dbt_failures else "[success]0[/success]"),
        )
        layout["footer"].update(Panel(footer_grid, border_style="dim"))

        return layout

    try:
        with Live(console=console, refresh_per_second=1, screen=True) as live:
            while True:
                new_batches = client.get_recent_batches(
                    pipeline_id=pipeline_id,
                    limit=5,
                )
                # Merge new batches into history (dedupe by batch_id)
                existing_ids = {b.get("batch_id") for b in batch_history}
                for b in new_batches:
                    if b.get("batch_id") not in existing_ids:
                        batch_history.append(b)

                live.update(_build_display())
                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[muted]Watch stopped.[/muted]")