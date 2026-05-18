# cli/commands/lifecycle.py
"""
Lifecycle commands — ude up / down / status / seed / init

ude up is fully self-contained — no make dependency.
Correct startup sequence with readiness checks at every step:
  1. MiniSky (wait for :8080)
  2. Auto-provision Pub/Sub topics for all registered pipelines
  3. dbt deps (skipped if packages already installed)
  4. FastAPI (wait for /health)
  5. Streamlit UI (background)
  6. Monitoring stack (Prometheus + Pushgateway + Grafana via Docker)

One command. No make. No separate provision. No separate observe start.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.panel import Panel
from rich.table import Table

from cli.core.checks import (
    assert_project_exists,
    minisky_is_alive,
    stack_is_running,
)
from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Stack lifecycle — up, down, status, seed, init")

# Monitoring compose file — written to ~/.ude/ so it works for pip users
_MONITORING_COMPOSE_PATH = Path.home() / ".ude" / "monitoring-compose.yml"
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


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude up ────────────────────────────────────────────────────────────────────

@app.command()
def up(ctx: typer.Context) -> None:
    """
    Start the full UDE stack — one command, no make required.

    Sequence (with readiness checks):
      1. MiniSky       — local GCP emulator
      2. Provisioning  — Pub/Sub topics for all registered pipelines
      3. dbt deps      — skipped if packages already installed
      4. FastAPI        — control plane API
      5. Streamlit UI  — operator dashboard
      6. Monitoring    — Prometheus + Pushgateway + Grafana
    """
    ude_ctx = _ctx(ctx)
    cfg     = ude_ctx.config

    console.print()
    console.print(Panel(
        "[bold]Starting Unified Data Engine[/bold]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    # ── Step 1: MiniSky ───────────────────────────────────────────────────────
    _step(1, 6, "MiniSky", "local GCP emulator")
    if _port_open(8080):
        print_success("MiniSky already running at :8080")
    else:
        _bg("minisky start")
        ok = _wait_for_port(8080, timeout=20, label="MiniSky")
        if not ok:
            print_error("MiniSky failed to start. Check Docker is running.")
            raise typer.Exit(code=1)
        print_success("MiniSky ready at http://localhost:8080")

    # ── Step 2: Provision ─────────────────────────────────────────────────────
    _step(2, 6, "Provisioning", "Pub/Sub topics + BigQuery datasets")
    _provision(cfg)

    # ── Step 3: dbt deps ──────────────────────────────────────────────────────
    _step(3, 6, "dbt packages", "skipped if already installed")
    _ensure_dbt_deps()

    # ── Step 4: FastAPI ───────────────────────────────────────────────────────
    _step(4, 6, "FastAPI", "control plane API")
    if _port_open(8000):
        print_success("API already running at :8000")
    else:
        _start_api()
        ok = _wait_for_url(
            f"{cfg.api_base_url}/health",
            timeout=15,
            label="FastAPI",
        )
        if not ok:
            print_error("FastAPI failed to start.")
            raise typer.Exit(code=1)
        print_success(f"API ready at {cfg.api_base_url}/docs")

    # ── Step 5: Streamlit UI ──────────────────────────────────────────────────
    _step(5, 6, "Streamlit UI", "operator dashboard")
    if _port_open(8501):
        print_success("Streamlit already running at :8501")
    else:
        _start_streamlit()
        ok = _wait_for_port(8501, timeout=15, label="Streamlit")
        if ok:
            print_success("Streamlit ready at http://localhost:8501")
        else:
            print_warning("Streamlit slow to start — check with: ude status")

    # ── Step 6: Monitoring stack ──────────────────────────────────────────────
    _step(6, 6, "Monitoring", "Prometheus + Pushgateway + Grafana")
    if _port_open(9090) and _port_open(3000):
        print_success("Monitoring already running (Grafana at :3000)")
    else:
        _start_monitoring()

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[success]✓[/success] UDE stack is up.\n\n"
        f"  API       → [bold]{cfg.api_base_url}/docs[/bold]\n"
        f"  Dashboard → [bold]http://localhost:8501[/bold]\n"
        f"  Grafana   → [bold]http://localhost:3000[/bold]  [muted](admin / admin)[/muted]\n\n"
        f"  Run: [bold]ude status[/bold] to verify all components\n"
        f"  Run: [bold]ude observe watch[/bold] for live batch feed",
        title="[bold]Stack ready[/bold]",
        border_style="green",
        padding=(1, 2),
    ))
    console.print()


# ── ude down ──────────────────────────────────────────────────────────────────

@app.command()
def down(ctx: typer.Context) -> None:
    """Stop the full UDE stack."""
    console.print()
    print_info("Stopping UDE stack...")

    stopped = []

    # Stop engine
    r = subprocess.run(
        ["pkill", "-f", "engine/main.py"],
        capture_output=True,
    )
    if r.returncode == 0:
        stopped.append("engine")

    # Stop API
    r = subprocess.run(
        ["pkill", "-f", "uvicorn api.main"],
        capture_output=True,
    )
    if r.returncode == 0:
        stopped.append("API")

    # Stop Streamlit
    r = subprocess.run(
        ["pkill", "-f", "streamlit run"],
        capture_output=True,
    )
    if r.returncode == 0:
        stopped.append("Streamlit")

    # Stop monitoring
    if _MONITORING_COMPOSE_PATH.exists():
        subprocess.run(
            ["docker", "compose", "-f", str(_MONITORING_COMPOSE_PATH), "down"],
            capture_output=True,
        )
        stopped.append("monitoring")

    if stopped:
        print_success(f"Stopped: {', '.join(stopped)}")
    else:
        print_info("Nothing was running.")

    console.print()


# ── ude status ────────────────────────────────────────────────────────────────

@app.command()
def status(ctx: typer.Context) -> None:
    """Show health of every component."""
    ude_ctx = _ctx(ctx)
    cfg     = ude_ctx.config

    import shutil

    rows = [
        ("API stack",  stack_is_running(cfg),          f"{cfg.api_base_url}/health"),
        ("MiniSky",    minisky_is_alive(cfg),           cfg.minisky_url),
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

    project_str = (
        f"[info]{cfg.project_name}[/info] [muted]({cfg.project_token})[/muted]"
        if cfg.has_project
        else "[warning]No project — run ude init[/warning]"
    )

    console.print()
    console.print(Panel(
        table,
        title=(
            f"[bold]UDE Status[/bold] · env=[info]{cfg.env}[/info]"
            f" · project={project_str}"
        ),
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
    ude_ctx = _ctx(ctx)

    if not minisky_is_alive(ude_ctx.config):
        print_error("MiniSky is not running. Start it with: ude up")
        raise typer.Exit(code=1)

    cmd = "make seed"
    if scenario:
        cmd = f"python data-generator/scenarios/{scenario}.py"

    print_info(f"Seeding data ({scenario or 'all scenarios'})...")
    result = subprocess.run(cmd, shell=True)
    if result.returncode == 0:
        print_success("Data published to Pub/Sub.")
    else:
        print_error("Seed failed — check MiniSky is provisioned: ude up")
        raise typer.Exit(code=result.returncode)


# ── ude init ──────────────────────────────────────────────────────────────────

@app.command()
def init(ctx: typer.Context) -> None:
    """
    Scaffold a new UDE project and generate a project token.

    The project token scopes all your pipelines — only your pipelines
    are visible when you run ude pipeline list.
    """
    from cli.scaffold.project import scaffold_project
    from cli.core.config import (
        generate_token, write_config,
        config_exists, _load_file,
    )

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
        type=typer.Choice(["local", "staging", "production"]),
    )
    gcp_project  = typer.prompt(
        "GCP project ID (leave blank for MiniSky local dev)", default=""
    )

    token = generate_token(project_name)

    scaffold_project(
        target_dir=cwd,
        project_name=project_name,
        env=env,
        gcp_project=gcp_project or "minisky-local",
    )

    existing_cfg = _load_file() if config_exists() else {}
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
    print_info("Next step: [bold]ude up[/bold]")
    console.print()


# ── Private helpers ───────────────────────────────────────────────────────────

def _step(n: int, total: int, name: str, description: str) -> None:
    """Print a step header."""
    console.print(
        f"  [muted][{n}/{total}][/muted] [bold]{name}[/bold]"
        f" [muted]— {description}[/muted]"
    )


def _port_open(port: int) -> bool:
    """Check if something is listening on localhost:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("localhost", port)) == 0


def _wait_for_port(
    port: int,
    timeout: int = 20,
    label: str = "",
    interval: float = 1.0,
) -> bool:
    """Poll until port is open or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(interval)
    print_warning(f"{label} not ready after {timeout}s")
    return False


def _wait_for_url(
    url: str,
    timeout: int = 15,
    label: str = "",
    interval: float = 1.0,
) -> bool:
    """Poll URL until it returns 2xx or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0, follow_redirects=True)
            if r.status_code < 400:
                return True
        except Exception:
            pass
        time.sleep(interval)
    print_warning(f"{label} not ready after {timeout}s")
    return False


def _bg(cmd: str) -> None:
    """Run a shell command in the background."""
    subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _provision(cfg) -> None:
    """
    Provision Pub/Sub topics and BigQuery datasets on MiniSky.

    Reads ALL registered pipelines — filesystem AND every API-registered
    pipeline across all project tokens — and creates topics/subscriptions.
    Idempotent — safe to run on every startup.
    """
    import urllib.request
    import json
    import logging as _logging

    minisky = cfg.minisky_url
    project = "local-dev-project"

    # Suppress INFO logs from loader and bigtable during this step
    for _log_name in ("config.loader", "engine.state.bigtable_client"):
        _logging.getLogger(_log_name).setLevel(_logging.WARNING)

    # Collect pipelines from ALL sources:
    #   1. Filesystem (config/pipelines/*.yml)
    #   2. ALL Bigtable keys — across every project token
    #      (load_pipelines() with a token only returns that token's pipelines,
    #       so we scan Bigtable directly to get everything)
    pipelines = []
    seen_ids  = set()

    # Filesystem pipelines
    try:
        from config.loader import _load_from_filesystem
        for p in _load_from_filesystem():
            pid = p.get("pipeline_id")
            if pid and pid not in seen_ids:
                pipelines.append(p)
                seen_ids.add(pid)
    except Exception:
        pass

    # All Bigtable pipeline_config# keys — regardless of token namespace
    try:
        from engine.state.bigtable_client import BigtableClient
        client   = BigtableClient()
        all_keys = client.all_keys()
        for key in all_keys:
            if not key.startswith("pipeline_config#"):
                continue
            config = client.get(key)
            if not config or not isinstance(config, dict):
                continue
            pid = config.get("pipeline_id")
            if pid and pid not in seen_ids:
                pipelines.append(config)
                seen_ids.add(pid)
    except Exception:
        pass

    # Restore log levels
    for _log_name in ("config.loader", "engine.state.bigtable_client"):
        _logging.getLogger(_log_name).setLevel(_logging.INFO)

    # Always create the standard BigQuery datasets
    datasets = ["raw_staging", "snapshots", "marts", "quarantine"]
    for ds in datasets:
        try:
            body = json.dumps({
                "datasetReference": {
                    "datasetId": ds,
                    "projectId": project,
                }
            }).encode()
            req = urllib.request.Request(
                f"{minisky}/bigquery/v2/projects/{project}/datasets",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # already exists or not critical

    # Create topics and subscriptions for each pipeline
    created_topics = []
    created_subs   = []

    for pipeline in pipelines:
        pid = pipeline.get("pipeline_id", "")
        sub = pipeline.get("subscription_id", f"raw.{pid}-sub")

        # Derive topic from subscription (raw.customers-sub → raw.customers)
        topic = sub.replace("-sub", "")

        # Create topic
        try:
            req = urllib.request.Request(
                f"{minisky}/v1/projects/{project}/topics/{topic}",
                data=b"{}",
                method="PUT",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            created_topics.append(topic)
        except Exception as e:
            # 409 = already exists — count as success (idempotent)
            if "409" in str(e) or "Conflict" in str(e):
                created_topics.append(topic)
            else:
                import sys
                print(f"    [warn] topic {topic}: {e}", file=sys.stderr)

        # Create subscription
        try:
            body = json.dumps({
                "topic": f"projects/{project}/topics/{topic}",
                "ackDeadlineSeconds": 60,
            }).encode()
            req = urllib.request.Request(
                f"{minisky}/v1/projects/{project}/subscriptions/{sub}",
                data=body,
                method="PUT",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            created_subs.append(sub)
        except Exception as e:
            # 409 = already exists — count as success (idempotent)
            if "409" in str(e) or "Conflict" in str(e):
                created_subs.append(sub)
            else:
                import sys
                print(f"    [warn] subscription {sub}: {e}", file=sys.stderr)

    n_topics = len(created_topics)
    n_subs   = len(created_subs)
    n_ds     = len(datasets)
    n_total  = len(pipelines)

    print_success(
        f"Verified {n_topics}/{n_total} topic(s) · "
        f"{n_subs}/{n_total} subscription(s) · "
        f"{n_ds} datasets ready"
    )


def _ensure_dbt_deps() -> None:
    """
    Install dbt packages — skip if dbt_packages/ already exists and is populated.
    Prevents blocking on network failures at startup.
    """
    packages_dir = Path("dbt/dbt_packages")

    if packages_dir.exists() and any(packages_dir.iterdir()):
        print_success("dbt packages already installed — skipping")
        return

    print_info("Installing dbt packages...")
    result = subprocess.run(
        ["dbt", "deps", "--project-dir", "dbt", "--profiles-dir", "dbt", "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        print_success("dbt packages installed")
    else:
        print_warning(
            "dbt deps failed (network issue?) — continuing without packages. "
            "Run: ude dbt run to retry."
        )


def _start_api() -> None:
    """Start FastAPI in the background."""
    python = sys.executable
    subprocess.Popen(
        [
            python, "-m", "uvicorn",
            "api.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--log-level", "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(Path.cwd()),
    )


def _start_streamlit() -> None:
    """Start Streamlit in the background."""
    python = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())

    # Find streamlit — prefer venv binary
    streamlit = Path(python).parent / "streamlit"
    if not streamlit.exists():
        import shutil
        found = shutil.which("streamlit")
        if not found:
            print_warning("streamlit not found — skipping UI")
            return
        streamlit = Path(found)

    ui_path = Path("ui/app.py")
    if not ui_path.exists():
        print_warning("ui/app.py not found — skipping UI")
        return

    subprocess.Popen(
        [
            str(streamlit), "run", str(ui_path),
            "--server.port", "8501",
            "--server.address", "0.0.0.0",
            "--server.headless", "true",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=str(Path.cwd()),
    )


def _start_monitoring() -> None:
    """Start Prometheus + Pushgateway + Grafana via Docker compose."""
    # Check Docker is available
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        timeout=5,
    )
    if result.returncode != 0:
        print_warning("Docker not available — skipping monitoring stack")
        print_info("Install Docker Desktop and run: ude observe start")
        return

    _MONITORING_COMPOSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MONITORING_COMPOSE_PATH.write_text(_MONITORING_COMPOSE)

    result = subprocess.run(
        ["docker", "compose", "-f", str(_MONITORING_COMPOSE_PATH), "up", "-d"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode == 0:
        # Wait for Grafana
        ok = _wait_for_port(3000, timeout=15, label="Grafana")
        if ok:
            print_success("Monitoring ready — Grafana at http://localhost:3000")
        else:
            print_warning("Monitoring starting slowly — check with: ude status")
    else:
        print_warning("Monitoring stack failed to start — run: ude observe start")