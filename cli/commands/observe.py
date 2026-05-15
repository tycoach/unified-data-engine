# cli/commands/observe.py
"""
ude observe — live terminal observability.

Commands:
    ude observe start    — start Prometheus + Pushgateway + Grafana via Docker
    ude observe stop     — stop the monitoring stack
    ude observe logs     — stream engine logs to the terminal
    ude observe metrics  — snapshot current Prometheus metrics as a table
    ude observe watch    — live dashboard: batch cycles, test results, record counts
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import typer
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from cli.core.checks import assert_stack_running
from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Observability — start, stop, logs, metrics, watch")

# Minimal docker-compose for the monitoring stack
# Self-contained — no engine filesystem access required
_MONITORING_COMPOSE = """\
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: ude_prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.enable-lifecycle'
      - '--storage.tsdb.retention.time=7d'
    volumes:
      - ude_prometheus_data:/prometheus
    restart: unless-stopped

  pushgateway:
    image: prom/pushgateway:latest
    container_name: ude_pushgateway
    ports:
      - "9091:9091"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: ude_grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
    volumes:
      - ude_grafana_data:/var/lib/grafana
    depends_on:
      - prometheus
    restart: unless-stopped

volumes:
  ude_prometheus_data:
  ude_grafana_data:
"""

# Store compose file in ~/.ude/ so it persists across sessions
_COMPOSE_PATH = Path.home() / ".ude" / "monitoring-compose.yml"


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude observe start ─────────────────────────────────────────────────────────

@app.command(name="start")
def start(ctx: typer.Context) -> None:
    """
    Start the UDE monitoring stack — Prometheus, Pushgateway, and Grafana.

    Works for 3rd party pip installs — generates a self-contained
    docker-compose.yml in ~/.ude/ and starts it with Docker.
    No access to the engine filesystem required.
    """
    # Check Docker is available
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        print_error("Docker is not running. Start Docker Desktop and try again.")
        raise typer.Exit(code=1)

    # Write compose file to ~/.ude/
    _COMPOSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COMPOSE_PATH.write_text(_MONITORING_COMPOSE)

    print_info("Starting monitoring stack (Prometheus + Pushgateway + Grafana)...")

    result = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_PATH), "up", "-d"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print_error("Failed to start monitoring stack.")
        console.print(result.stderr)
        raise typer.Exit(code=1)

    # Wait for services to be ready
    print_info("Waiting for services to be ready...")
    time.sleep(4)

    print_success("Monitoring stack is running.")
    console.print()
    console.print("    [bold]Prometheus[/bold]  → http://localhost:9090")
    console.print("    [bold]Pushgateway[/bold] → http://localhost:9091")
    console.print("    [bold]Grafana[/bold]     → http://localhost:3000  [muted](admin / admin)[/muted]")
    console.print()
    print_info("Compose file saved to: ~/.ude/monitoring-compose.yml")
    print_info("Stop with: ude observe stop")


# ── ude observe stop ──────────────────────────────────────────────────────────

@app.command(name="stop")
def stop(ctx: typer.Context) -> None:
    """Stop the UDE monitoring stack."""
    if not _COMPOSE_PATH.exists():
        print_warning("No monitoring stack compose file found at ~/.ude/monitoring-compose.yml")
        print_info("Start it first with: ude observe start")
        raise typer.Exit()

    print_info("Stopping monitoring stack...")
    result = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_PATH), "down"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print_error("Failed to stop monitoring stack.")
        console.print(result.stderr)
        raise typer.Exit(code=1)

    print_success("Monitoring stack stopped.")


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
    """Stream engine logs to the terminal."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.observe import ObserveClient
    client = ObserveClient(ude_ctx.config)

    level_style = {
        "DEBUG":    "dim",
        "INFO":     "cyan",
        "WARNING":  "yellow",
        "ERROR":    "bold red",
        "CRITICAL": "bold red on white",
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

            pid_tag = f" [pipeline]{pid}[/pipeline]" if pid else ""
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
        table = Table(
            show_header=True, header_style="bold",
            box=None, padding=(0, 2)
        )
        table.add_column("Metric",   style="muted",    min_width=40)
        table.add_column("Pipeline", style="pipeline", min_width=14)
        table.add_column("Value",    justify="right",  min_width=8)
        table.add_column("Labels",   style="dim")

        metrics_list = data.get("metrics", [])
        if not metrics_list:
            table.add_row(
                "[muted]No metrics yet — run make seed to generate data[/muted]",
                "", "", ""
            )

        for m in metrics_list:
            table.add_row(
                m.get("name", "—"),
                m.get("pipeline", "—"),
                str(m.get("value", "—")),
                m.get("labels", ""),
            )

        source = data.get("source", "pushgateway")
        error  = data.get("error")
        title  = f"[bold]UDE Metrics[/bold]" \
                 + (f" · [pipeline]{pipeline_id}[/pipeline]" if pipeline_id else "") \
                 + f" [muted]{data.get('scraped_at', '')}[/muted]"
        if error:
            title += f" [error]⚠ {error}[/error]"

        return Panel(table, title=title, border_style="cyan", padding=(1, 2))

    if not watch:
        data = client.get_metrics(pipeline_id=pipeline_id)
        console.print()
        console.print(_render(data))
        console.print()
        return

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
    Live batch feed — records, dbt results, schema status, quarantine rate.
    Press Ctrl+C to exit.
    """
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.observe import ObserveClient
    from cli.output.live import build_watch_layout
    client = ObserveClient(ude_ctx.config)

    print_info(
        "Live batch watch"
        + (f" · pipeline={pipeline_id}" if pipeline_id else " · all pipelines")
        + f" · refreshing every {interval}s · Ctrl+C to stop"
    )
    console.print()

    batch_history: list[dict] = []

    try:
        with Live(
            console=console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            while True:
                new_batches = client.get_recent_batches(
                    pipeline_id=pipeline_id,
                    limit=5,
                )
                existing_ids = {b.get("batch_id") for b in batch_history}
                for b in new_batches:
                    if b.get("batch_id") not in existing_ids:
                        batch_history.append(b)

                live.update(build_watch_layout(
                    batch_history=batch_history,
                    pipeline_id=pipeline_id,
                    interval=interval,
                ))
                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[muted]Watch stopped.[/muted]")