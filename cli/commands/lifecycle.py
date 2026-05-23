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
  6. Monitoring stack + provision Prometheus datasource + import dashboards
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

import httpx
import logging
import typer

logging.getLogger('httpx').setLevel(logging.WARNING)
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

_MONITORING_COMPOSE_PATH = Path.home() / ".ude" / "monitoring-compose.yml"
_PROMETHEUS_CONFIG = """global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: pushgateway
    honor_labels: true
    static_configs:
      - targets: ["pushgateway:9091"]
"""

_MONITORING_COMPOSE = """services:
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
      - /home/taiwohassan/.ude/prometheus.yml:/etc/prometheus/prometheus.yml:ro
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
      - GF_SECURITY_ADMIN_PASSWORD={grafana_password}
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

# Grafana API credentials
_PROMETHEUS_CONFIG_PATH = Path.home() / ".ude" / "prometheus.yml"
_PROMETHEUS_CONFIG = """\
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: pushgateway
    honor_labels: true
    static_configs:
      - targets: ["pushgateway:9091"]
"""

_GRAFANA_URL  = "http://localhost:3000"
_GRAFANA_AUTH = ("admin", "admin")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude up ────────────────────────────────────────────────────────────────────

@app.command()
def up(ctx: typer.Context) -> None:
    """
    Start the full UDE stack — one command, no make required.

    Sequence:
      1. MiniSky       — local GCP emulator
      2. Provisioning  — Pub/Sub topics for all registered pipelines
      3. dbt deps      — skipped if packages already installed
      4. FastAPI        — control plane API
      5. Streamlit UI  — operator dashboard
      6. Monitoring    — Prometheus + Grafana + pre-loaded dashboards
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
    _migrate_state_dir()  # one-time migration from .state/ to ~/.ude/state/
    _provision(cfg)

    # ── Step 3: dbt deps ──────────────────────────────────────────────────────
    _step(3, 6, "dbt packages", "skipped if already installed")
    _ensure_dbt_deps()

    # ── Step 4: FastAPI ───────────────────────────────────────────────────────
    _step(4, 6, "FastAPI", "control plane API")
    api_port = cfg.port if cfg.port else 8000
    if _port_open(api_port):
        print_success(f"API already running at {cfg.api_base_url}")
    elif _is_engine_owner():
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
    else:
        # API not running and we can't start it (not the engine owner)
        # This means the user needs to point their CLI at a running engine
        console.print()
        print_error(f"API not reachable at {cfg.api_base_url}")
        console.print()
        console.print("  [bold]To fix this, edit [info]~/.ude/config.yml[/info] and set:[/bold]")
        console.print()
        console.print("    [muted]host:[/muted]  [info]<engine-host>[/info]    [muted]# IP or hostname of the UDE engine[/muted]")
        console.print("    [muted]port:[/muted]  [info]8000[/info]             [muted]# or 8443 if engine uses HTTPS[/muted]")
        console.print()
        console.print("  [muted]If you are running your own engine:[/muted]")
        console.print("    git clone https://github.com/tycoach/unified-data-engine")
        console.print("    cd unified-data-engine && pip install -e '.[dev]'")
        console.print("    ude up")
        console.print()
        raise typer.Exit(code=1)

    # ── Step 5: Streamlit UI ──────────────────────────────────────────────────
    _step(5, 6, "Streamlit UI", "operator dashboard")
    if _port_open(8501):
        print_success("Streamlit already running at :8501")
    else:
        _start_streamlit()
        ok = _wait_for_port(8501, timeout=20, label="Streamlit")
        if ok:
            print_success("Streamlit ready at http://localhost:8501")
        else:
            print_warning("Streamlit slow to start — check with: ude status")

    # ── Step 6: Monitoring stack ──────────────────────────────────────────────
    _step(6, 6, "Monitoring", "Prometheus + Pushgateway + Grafana + dashboards")
    if _port_open(9090) and _port_open(3000):
        print_success("Monitoring already running — verifying dashboards...")
        _provision_grafana()
    else:
        _start_monitoring()

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[success]✓[/success] UDE stack is up.\n\n"
        f"  API       → [bold]{cfg.api_base_url}/docs[/bold]\n"
        f"  Dashboard → [bold]http://localhost:8501[/bold]\n"
        f"  Grafana   → [bold]http://localhost:3000[/bold]  [muted](admin / {_get_or_create_grafana_password()})[/muted]\n\n"
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

    for pattern in ["engine/main.py", "uvicorn api.main", "streamlit run"]:
        r = subprocess.run(["pkill", "-f", pattern], capture_output=True)
        if r.returncode == 0:
            stopped.append(pattern.split()[0])

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
        ("dbt",        _dbt_available(), "on PATH"),
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
        help="Scenario to seed. Defaults to all."
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
    """Scaffold a new UDE project and generate a project token."""
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
    env = typer.prompt(
        "Environment", default="local",
        type=typer.Choice(["local", "staging", "production"]),
    )
    gcp_project = typer.prompt(
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
        f"Share with teammates who need access to this project.\n"
        f"Set via env var: [bold]UDE_PROJECT_TOKEN={token}[/bold][/muted]",
        title="[bold]Project Identity[/bold]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()
    print_info("Next step: [bold]ude up[/bold]")
    console.print()


# ── Private helpers ───────────────────────────────────────────────────────────

def _dbt_available() -> bool:
    """Check if dbt is available — checks PATH and pipx/venv bin directory."""
    import shutil
    if shutil.which("dbt"):
        return True
    # Check in same bin dir as sys.executable (pipx venv)
    dbt_in_venv = Path(sys.executable).parent / "dbt"
    return dbt_in_venv.exists()


def _is_engine_owner() -> bool:
    """
    True if the UDE engine API is available — either:
      1. Running from the engine repo (api/main.py in cwd), or
      2. api.main is importable from the installed pip/pipx package

    This means pip/pipx users ARE the engine owner — the package
    ships with api/main.py and can start its own API server.
    No repo clone required.
    """
    # Check 1: running from engine repo (dev/contributor context)
    cwd = Path.cwd()
    if (cwd / "api" / "main.py").exists():
        return True

    # Check 2: api.main is importable from installed package (pip/pipx)
    try:
        import importlib.util
        spec = importlib.util.find_spec("api.main")
        return spec is not None
    except Exception:
        return False


def _get_or_create_grafana_password() -> str:
    """
    Get or generate the Grafana admin password.
    Stored in ~/.ude/config.yml as grafana_password.
    Generated once and reused on subsequent startups.
    """
    import yaml
    cfg_file = Path.home() / ".ude" / "config.yml"
    cfg      = {}

    if cfg_file.exists():
        try:
            with cfg_file.open() as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}

    if cfg.get("grafana_password"):
        return cfg["grafana_password"]

    # Generate a new password — 16 chars, alphanumeric
    import secrets, string
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(16))

    cfg["grafana_password"] = password
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    with cfg_file.open("w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    return password


def _step(n: int, total: int, name: str, description: str) -> None:
    console.print(
        f"  [muted][{n}/{total}][/muted] [bold]{name}[/bold]"
        f" [muted]— {description}[/muted]"
    )


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("localhost", port)) == 0


def _wait_for_port(port: int, timeout: int = 20, label: str = "", interval: float = 1.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(interval)
    print_warning(f"{label} not ready after {timeout}s")
    return False


def _wait_for_url(url: str, timeout: int = 15, label: str = "", interval: float = 1.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0, follow_redirects=True, verify=False)
            if r.status_code < 400:
                return True
        except Exception:
            pass
        time.sleep(interval)
    print_warning(f"{label} not ready after {timeout}s")
    return False


def _bg(cmd: str) -> None:
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _migrate_state_dir() -> None:
    """
    One-time migration: copy state files from old .state/ (relative to cwd)
    to new ~/.ude/state/ (absolute path).

    Safe to run on every startup — skips if already migrated or no old state.
    """
    import shutil as _shutil

    old_state = Path.cwd() / ".state"
    new_state  = Path.home() / ".ude" / "state"

    if not old_state.exists():
        return

    new_state.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for f in old_state.glob("*.json"):
        dest = new_state / f.name
        if not dest.exists():
            _shutil.copy2(f, dest)
            migrated += 1

    if migrated > 0:
        logger.info(f"[Main] Migrated {migrated} state files from .state/ to ~/.ude/state/")


def _provision(cfg) -> None:
    """Provision Pub/Sub topics + BigQuery datasets for all registered pipelines."""
    import logging as _logging

    minisky = cfg.minisky_url
    project = "local-dev-project"

    for _log_name in ("config.loader", "engine.state.bigtable_client"):
        _logging.getLogger(_log_name).setLevel(_logging.WARNING)

    pipelines = []
    seen_ids  = set()

    try:
        from config.loader import _load_from_filesystem
        for p in _load_from_filesystem():
            pid = p.get("pipeline_id")
            if pid and pid not in seen_ids:
                pipelines.append(p)
                seen_ids.add(pid)
    except Exception:
        pass

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

    for _log_name in ("config.loader", "engine.state.bigtable_client"):
        _logging.getLogger(_log_name).setLevel(_logging.INFO)

    datasets = ["raw_staging", "snapshots", "marts", "quarantine"]
    for ds in datasets:
        try:
            body = json.dumps({
                "datasetReference": {"datasetId": ds, "projectId": project}
            }).encode()
            req = urllib.request.Request(
                f"{minisky}/bigquery/v2/projects/{project}/datasets",
                data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    created_topics = []
    created_subs   = []

    for pipeline in pipelines:
        pid = pipeline.get("pipeline_id", "")
        sub = pipeline.get("subscription_id", f"raw.{pid}-sub")
        topic = sub.replace("-sub", "")

        try:
            req = urllib.request.Request(
                f"{minisky}/v1/projects/{project}/topics/{topic}",
                data=b"{}", method="PUT",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            created_topics.append(topic)
        except Exception as e:
            if "409" in str(e) or "Conflict" in str(e):
                created_topics.append(topic)

        try:
            body = json.dumps({
                "topic": f"projects/{project}/topics/{topic}",
                "ackDeadlineSeconds": 60,
            }).encode()
            req = urllib.request.Request(
                f"{minisky}/v1/projects/{project}/subscriptions/{sub}",
                data=body, method="PUT",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            created_subs.append(sub)
        except Exception as e:
            if "409" in str(e) or "Conflict" in str(e):
                created_subs.append(sub)

    n_total = len(pipelines)
    print_success(
        f"Verified {len(created_topics)}/{n_total} topic(s) · "
        f"{len(created_subs)}/{n_total} subscription(s) · "
        f"{len(datasets)} datasets ready"
    )


def _ensure_dbt_deps() -> None:
    """
    Ensure dbt is installed and dbt packages are up to date.

    Works for all install methods:
      - pipx install unified-data-engine  (no venv, dbt auto-installed)
      - pip install unified-data-engine   (venv, dbt auto-installed)
      - pip install -e ".[dev]"           (engine dev, dbt already present)

    Uses sys.executable to install dbt into whichever Python environment
    is running the CLI — pipx venv, user venv, or system Python.
    """
    import shutil

    dbt_bin = shutil.which("dbt")

    # dbt not found — install it into the current Python environment
    if not dbt_bin:
        print_info("dbt not found — installing into current environment...")
        install_result = subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "dbt-core>=1.8.0",
                "dbt-duckdb>=1.8.0",
                "--quiet",
                "--disable-pip-version-check",
            ],
            capture_output=True, text=True, timeout=120,
        )
        if install_result.returncode != 0:
            print_warning(
                "dbt install failed — some features unavailable. "
                "Install manually: pip install dbt-core dbt-duckdb"
            )
            return

        # Re-check after install
        # dbt may be in the same bin dir as sys.executable
        python_bin_dir = Path(sys.executable).parent
        dbt_bin = str(python_bin_dir / "dbt")
        if not Path(dbt_bin).exists():
            dbt_bin = shutil.which("dbt")

        if dbt_bin:
            print_success("dbt installed successfully")
        else:
            print_warning("dbt installed but not found on PATH — restart your shell if needed")
            return

    # Skip dbt deps if no dbt/ project directory exists
    dbt_project = Path("dbt")
    if not dbt_project.exists():
        print_success("dbt ready (no dbt/ project directory — skipping deps)")
        return

    # Skip if packages already installed
    packages_dir = Path("dbt/dbt_packages")
    if packages_dir.exists() and any(packages_dir.iterdir()):
        print_success("dbt packages already installed — skipping")
        return

    # Install dbt packages
    print_info("Installing dbt packages...")
    result = subprocess.run(
        [dbt_bin, "deps",
         "--project-dir", "dbt",
         "--profiles-dir", "dbt",
         "--quiet"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0:
        print_success("dbt packages installed")
    else:
        print_warning(
            "dbt deps failed (network issue?) — continuing without packages. "
            "Run: ude dbt run to retry."
        )


def _start_api() -> None:
    python = sys.executable
    port   = _get_api_port()

    # Ensure uvicorn + API dependencies are installed in current environment
    _ensure_api_deps()

    cmd = [
        python, "-m", "uvicorn", "api.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--log-level", "warning",
    ]

    # Add TLS args if cert exists
    tls_cert = Path.home() / ".ude" / "tls" / "server.crt"
    tls_key  = Path.home() / ".ude" / "tls" / "server.key"
    if tls_cert.exists() and tls_key.exists():
        cmd += ["--ssl-certfile", str(tls_cert), "--ssl-keyfile", str(tls_key)]
        print_info("HTTPS enabled — TLS certificate loaded")

    # Find the directory containing api/main.py
    # Works for both repo (cwd) and pip/pipx installs (site-packages)
    cwd = Path.cwd()
    if (cwd / "api" / "main.py").exists():
        api_cwd = str(cwd)
    else:
        try:
            import importlib.util
            spec    = importlib.util.find_spec("api.main")
            api_cwd = str(Path(spec.origin).parent.parent)
        except Exception:
            api_cwd = str(cwd)

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=api_cwd,
    )


def _ensure_api_deps() -> None:
    """
    Ensure uvicorn + FastAPI deps are installed in the current environment.
    Required for pipx users where uvicorn is not bundled by default.
    Uses sys.executable so packages land in the pipx venv.
    """
    import shutil
    if shutil.which("uvicorn") or (Path(sys.executable).parent / "uvicorn").exists():
        return

    print_info("Installing API server dependencies...")
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "uvicorn[standard]>=0.29.0",
            "fastapi>=0.111.0",
            "prometheus-client>=0.20.0",
            "python-multipart>=0.0.9",
            "--quiet",
            "--disable-pip-version-check",
        ],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0:
        print_success("API server dependencies installed")
    else:
        print_warning(
            "Could not install API dependencies. "
            "Install manually: pip install uvicorn fastapi"
        )


def _get_api_port() -> int:
    """Read port from ~/.ude/config.yml, default 8000."""
    try:
        import yaml
        cfg_file = Path.home() / ".ude" / "config.yml"
        if cfg_file.exists():
            with cfg_file.open() as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("port", 8000)
    except Exception:
        pass
    return 8000


def _start_streamlit() -> None:
    python = sys.executable
    env    = os.environ.copy()

    # Find ui/app.py — check cwd first, then installed package
    ui_path = Path("ui/app.py")
    if ui_path.exists():
        env["PYTHONPATH"] = str(Path.cwd())
    else:
        try:
            import importlib.util
            spec = importlib.util.find_spec("ui.app")
            if spec and spec.origin:
                ui_path = Path(spec.origin)
                env["PYTHONPATH"] = str(Path(spec.origin).parent.parent)
            else:
                print_success("Streamlit UI — not available in this environment")
                return
        except Exception:
            print_success("Streamlit UI — not available in this environment")
            return

    # Find or install streamlit binary
    streamlit = Path(python).parent / "streamlit"
    if not streamlit.exists():
        import shutil
        found = shutil.which("streamlit")
        if not found:
            print_info("Installing Streamlit...")
            subprocess.run(
                [python, "-m", "pip", "install", "streamlit>=1.35.0",
                 "--quiet", "--disable-pip-version-check"],
                capture_output=True, timeout=120,
            )
            streamlit = Path(python).parent / "streamlit"
            if not streamlit.exists():
                print_warning("streamlit not found — skipping UI")
                return
        else:
            streamlit = Path(found)

    subprocess.Popen(
        [str(streamlit), "run", str(ui_path),
         "--server.port", "8501",
         "--server.address", "0.0.0.0",
         "--server.headless", "true"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env, cwd=str(Path(ui_path).parent.parent),
    )


def _start_monitoring() -> None:
    """Start monitoring stack and provision Grafana datasource + dashboards."""
    result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
    if result.returncode != 0:
        print_warning("Docker not available — skipping monitoring stack")
        print_info("Install Docker Desktop and run: ude observe start")
        return

    _MONITORING_COMPOSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Write prometheus.yml with Pushgateway scrape config
    _PROMETHEUS_CONFIG_PATH.write_text(_PROMETHEUS_CONFIG)
    # Inject generated Grafana password into compose
    grafana_password = _get_or_create_grafana_password()
    compose_content  = _MONITORING_COMPOSE.replace(
        "{grafana_password}", grafana_password
    )
    _MONITORING_COMPOSE_PATH.write_text(compose_content)

    result = subprocess.run(
        ["docker", "compose", "-f", str(_MONITORING_COMPOSE_PATH), "up", "-d"],
        capture_output=True, text=True, timeout=60,
    )

    if result.returncode != 0:
        print_warning("Monitoring stack failed to start — run: ude observe start")
        return

    ok = _wait_for_url(
        f"{_GRAFANA_URL}/api/health",
        timeout=30,
        label="Grafana API",
    )
    if not ok:
        print_warning("Grafana slow to start — dashboards will load on next ude up")
        return

    # Extra wait for Grafana to finish initialising after health check passes
    time.sleep(3)
    _provision_grafana()


def _provision_grafana() -> None:
    """
    Provision Prometheus datasource and import UDE dashboards into Grafana.

    Dashboards are bundled as package data in cli/data/dashboards/.
    Works for pip installs — no engine filesystem access required.
    """
    import importlib.resources as pkg_resources

    grafana_url  = _GRAFANA_URL
    auth         = _GRAFANA_AUTH

    # Wait for Grafana API to be fully ready before provisioning
    ok = _wait_for_url(f"{grafana_url}/api/health", timeout=15, label="Grafana API")
    if not ok:
        print_warning("Grafana API not ready — skipping dashboard provisioning")
        return

    # ── 1. Add Prometheus datasource ─────────────────────────────────────────
    datasource = {
        "name":      "Prometheus",
        "type":      "prometheus",
        "url":       "http://host.docker.internal:9090",
        "access":    "proxy",
        "isDefault": True,
    }

    try:
        req = urllib.request.Request(
            f"{grafana_url}/api/datasources",
            data=json.dumps(datasource).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        import base64
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        # 409 = datasource already exists — that's fine
        if "409" not in str(e) and "already exists" not in str(e).lower():
            print_warning(f"Could not add Prometheus datasource: {e}")

    # ── 2. Import dashboards from package data ────────────────────────────────
    dashboard_files = _get_bundled_dashboards()
    imported = 0

    for name, dashboard_json in dashboard_files.items():
        try:
            payload = {
                "dashboard": dashboard_json,
                "overwrite": True,
                "folderId":  0,
            }
            req = urllib.request.Request(
                f"{grafana_url}/api/dashboards/import",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            req.add_header("Authorization", f"Basic {token}")
            urllib.request.urlopen(req, timeout=5)
            imported += 1
        except Exception as e:
            print_warning(f"Could not import dashboard '{name}': {e}")

    grafana_password = _get_or_create_grafana_password()
    if imported > 0:
        print_success(
            f"Grafana ready — {imported} dashboard(s) imported · "
            f"http://localhost:3000  [muted](admin / {grafana_password})[/muted]"
        )
    else:
        print_success(
            f"Grafana ready at http://localhost:3000  "
            f"[muted](admin / {grafana_password})[/muted]"
        )


def _get_bundled_dashboards() -> dict[str, dict]:
    """
    Load dashboard JSON files bundled with the CLI package.

    Files are stored in cli/data/dashboards/ and included in the
    wheel via pyproject.toml include pattern.

    Falls back to monitoring/grafana/dashboards/ if running from
    the engine repo (contributors / self-hosted).
    """
    dashboards = {}

    # Try package data first (pip install path)
    try:
        import importlib.resources as pkg_resources
        
        pkg = pkg_resources.files("cli") / "data" / "dashboards"
        for resource in pkg.iterdir():
            if resource.name.endswith(".json"):
                content = json.loads(resource.read_text())
                dashboards[resource.name] = content
        if dashboards:
            return dashboards
    except Exception:
        pass

    # Fallback to engine repo path (contributors)
    repo_path = Path("monitoring/grafana/dashboards")
    if repo_path.exists():
        for f in repo_path.glob("*.json"):
            try:
                dashboards[f.name] = json.loads(f.read_text())
            except Exception:
                pass

    return dashboards