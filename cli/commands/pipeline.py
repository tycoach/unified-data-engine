# cli/commands/pipeline.py
"""
ude pipeline — pipeline management commands.

Commands:
    ude pipeline list              — list all registered pipelines + status
    ude pipeline inspect <id>      — show full config + last batch stats
    ude pipeline new               — scaffold YAML + dbt model stubs + register with engine
    ude pipeline register <id>     — register an existing local YAML with the engine
    ude pipeline enable  <id>      — resume a paused pipeline
    ude pipeline disable <id>      — pause a pipeline without deleting it
    ude pipeline delete  <id>      — deregister a pipeline entirely
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import typer
from rich.panel import Panel
from rich.table import Table

from cli.core.checks import assert_project_exists, assert_stack_running, stack_is_running
from cli.core.context import UDEContext
from cli.core.errors import PipelineNotFoundError
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Pipeline management — list, inspect, new, register, enable, disable, delete")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude pipeline list ─────────────────────────────────────────────────────────

@app.command(name="list")
def list_pipelines(ctx: typer.Context) -> None:
    """List all registered pipelines with their current status."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.pipeline import PipelineClient
    client    = PipelineClient(ude_ctx.config)
    pipelines = client.list()

    if not pipelines:
        print_warning("No pipelines registered yet.")
        print_info("Register one with: ude pipeline new")
        return

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
    )
    table.add_column("Pipeline ID",   style="pipeline")
    table.add_column("SCD Type",      justify="center")
    table.add_column("Status")
    table.add_column("Source",        style="muted")
    table.add_column("Schema ver",    justify="center")
    table.add_column("Last batch",    style="muted")
    table.add_column("Records",       justify="right")

    for p in pipelines:
        status_str = (
            "[success]● active[/success]"
            if p.get("enabled", True)
            else "[warning]○ paused[/warning]"
        )
        source = p.get("registered_via", "filesystem")
        source_str = "[info]api[/info]" if source == "api" else "[muted]filesystem[/muted]"

        table.add_row(
            p.get("pipeline_id", "—"),
            f"Type {p.get('scd_type', '?')}",
            status_str,
            source_str,
            str(p.get("schema_version", "—")),
            p.get("last_batch_at", "—"),
            str(p.get("last_batch_records", "—")),
        )

    console.print()
    console.print(Panel(
        table,
        title=f"[bold]Pipelines[/bold] ({len(pipelines)} registered)",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


# ── ude pipeline inspect ──────────────────────────────────────────────────────

@app.command(name="inspect")
def inspect(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to inspect"),
) -> None:
    """Show full config, schema fields, and last batch stats for a pipeline."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.pipeline import PipelineClient
    client = PipelineClient(ude_ctx.config)
    p = client.fetch(pipeline_id)

    if not p:
        raise PipelineNotFoundError(pipeline_id)

    # Config panel
    config_table = Table.grid(padding=(0, 2))
    config_table.add_column(style="muted", min_width=20)
    config_table.add_column(style="bold")

    config_rows = [
        ("Pipeline ID",      p.get("pipeline_id", "—")),
        ("SCD type",         f"Type {p.get('scd_type', '?')}"),
        ("Subscription",     p.get("subscription_id", "—")),
        ("Natural key",      p.get("natural_key", "—")),
        ("Null threshold",   str(p.get("null_threshold", "—"))),
        ("Late arrival",     p.get("late_arrival_window", "—")),
        ("Duplicate window", p.get("duplicate_window", "—")),
        ("Edge case mode",   p.get("edge_case_mode", "—")),
        ("Schema version",   str(p.get("schema_version", "—"))),
        ("Schema locked at", p.get("schema_locked_at", "—")),
        ("Registered via",   p.get("registered_via", "filesystem")),
        ("Status",           "active" if p.get("enabled", True) else "paused"),
    ]
    for label, value in config_rows:
        config_table.add_row(label, value)

    console.print()
    console.print(Panel(
        config_table,
        title=f"[pipeline]{pipeline_id}[/pipeline] · config",
        border_style="magenta",
        padding=(1, 2),
    ))

    # Schema fields
    fields = p.get("fields", {})
    if fields:
        field_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        field_table.add_column("Field")
        field_table.add_column("Type")
        field_table.add_column("Nullable", justify="center")

        for fname, fmeta in fields.items():
            nullable = "[muted]yes[/muted]" if fmeta.get("nullable") else "[bold]no[/bold]"
            field_table.add_row(fname, fmeta.get("type", "—"), nullable)

        console.print(Panel(
            field_table,
            title=f"[pipeline]{pipeline_id}[/pipeline] · schema fields",
            border_style="blue",
            padding=(1, 2),
        ))

    # Last batch
    batch = p.get("last_batch", {})
    if batch:
        batch_table = Table.grid(padding=(0, 2))
        batch_table.add_column(style="muted", min_width=20)
        batch_table.add_column()

        batch_rows = [
            ("Batch ID",            batch.get("batch_id", "—")),
            ("Processed at",        batch.get("processed_at", "—")),
            ("Records clean",       str(batch.get("records_clean", "—"))),
            ("Records quarantined", str(batch.get("records_quarantined", "—"))),
            ("dbt run",             "[success]pass[/success]" if batch.get("dbt_passed") else "[error]fail[/error]"),
            ("Snapshot opened",     str(batch.get("snapshot_opened", "—"))),
            ("Snapshot closed",     str(batch.get("snapshot_closed", "—"))),
        ]
        for label, value in batch_rows:
            batch_table.add_row(label, value)

        console.print(Panel(
            batch_table,
            title=f"[pipeline]{pipeline_id}[/pipeline] · last batch",
            border_style="cyan",
            padding=(1, 2),
        ))

    console.print()


# ── ude pipeline new ──────────────────────────────────────────────────────────

@app.command(name="new")
def new(
    ctx: typer.Context,
    pipeline_id: Optional[str] = typer.Option(
        None, "--id",
        help="Pipeline ID. Prompted if not provided."
    ),
) -> None:
    """
    Scaffold a new pipeline and register it with the engine.

    Creates local files:
      - config/pipelines/{id}.yml
      - dbt/models/staging/{id}_staged.sql
      - dbt/models/marts/dim_{id}.sql
      - dbt/snapshots/{id}_snapshot.sql  (SCD Type 2 only)

    Then registers the pipeline via POST /pipeline/ so the engine
    picks it up on its next cycle — no engine restart needed.
    """
    ude_ctx = _ctx(ctx)

    console.print()
    console.print("[bold]New Pipeline[/bold]")
    console.print("[muted]Answer a few questions to scaffold your pipeline.[/muted]")
    console.print()

    pid           = pipeline_id or typer.prompt("Pipeline ID (e.g. customers)")
    pid           = pid.strip().lower().replace("-", "_")
    natural_key   = typer.prompt(f"Natural key field for {pid}", default=f"{pid.rstrip('s')}_id")
    scd_type      = typer.prompt("SCD type", default="2", type=click.Choice(["1", "2"]))
    subscription  = typer.prompt("Pub/Sub subscription ID", default=f"raw.{pid}-sub")
    null_threshold = typer.prompt("Null threshold (0.0–1.0)", default="0.05")
    late_arrival  = typer.prompt("Late arrival window", default="24h")
    dup_window    = typer.prompt("Duplicate detection window", default="30m")

    console.print()
    print_info("Define schema fields. Type [bold]done[/bold] when finished.\n")

    fields: dict[str, dict] = {}
    while True:
        fname = typer.prompt("Field name (or 'done')", default="done")
        if fname.strip().lower() == "done":
            break
        ftype    = typer.prompt(f"  Type for {fname}", default="string",
                                type=click.Choice(["string", "integer", "float", "boolean", "datetime"]))
        nullable = typer.confirm(f"  Is {fname} nullable?", default=True)
        fields[fname] = {"type": ftype, "nullable": nullable}

    if "updated_at" not in fields:
        fields["updated_at"] = {"type": "datetime", "nullable": False}
        print_info("Auto-added 'updated_at' field (required by dbt snapshot strategy).")

    # Scaffold local files
    from cli.scaffold.pipeline import scaffold_pipeline
    scaffold_pipeline(
        pipeline_id=pid,
        natural_key=natural_key,
        scd_type=int(scd_type),
        subscription_id=subscription,
        null_threshold=float(null_threshold),
        late_arrival_window=late_arrival,
        duplicate_window=dup_window,
        fields=fields,
    )

    print_success(f"Pipeline '{pid}' scaffolded locally.")
    console.print(f"    [muted]config/pipelines/{pid}.yml[/muted]")
    console.print(f"    [muted]dbt/models/staging/{pid}_staged.sql[/muted]")
    console.print(f"    [muted]dbt/models/marts/dim_{pid}.sql[/muted]")
    if scd_type == "2":
        console.print(f"    [muted]dbt/snapshots/{pid}_snapshot.sql[/muted]")

    # Register with engine if stack is running
    console.print()
    if stack_is_running(ude_ctx.config):
        print_info("Stack is running — registering pipeline with engine...")
        _register_with_engine(
            ude_ctx=ude_ctx,
            pipeline_id=pid,
            natural_key=natural_key,
            scd_type=int(scd_type),
            subscription_id=subscription,
            null_threshold=float(null_threshold),
            late_arrival_window=late_arrival,
            duplicate_window=dup_window,
            fields=fields,
        )
    else:
        print_warning("Stack is not running — pipeline saved locally only.")
        print_info("Register with engine later: ude pipeline register " + pid)

    console.print()
    console.print(f"  Next: add [bold]{pid}_staged[/bold] to dbt/models/staging/_sources.yml")
    console.print(f"  Then: [bold]ude dbt run --select staging.{pid}_staged[/bold]")
    console.print()


# ── ude pipeline register ─────────────────────────────────────────────────────

@app.command(name="register")
def register(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to register with the engine"),
) -> None:
    """
    Register an existing local pipeline YAML with the running engine.

    Use this if you created a pipeline while the stack was down
    and want to register it now without running ude pipeline new again.
    """
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    # Read the local YAML
    yaml_path = Path(f"config/pipelines/{pipeline_id}.yml")
    if not yaml_path.exists():
        print_error(f"config/pipelines/{pipeline_id}.yml not found.")
        print_info("Create it first with: ude pipeline new")
        raise typer.Exit(code=1)

    import yaml
    with yaml_path.open() as f:
        config = yaml.safe_load(f)

    _register_with_engine(
        ude_ctx=ude_ctx,
        pipeline_id=config.get("pipeline_id", pipeline_id),
        natural_key=config.get("natural_key", ""),
        scd_type=config.get("scd_type", 2),
        subscription_id=config.get("subscription_id", ""),
        null_threshold=config.get("null_threshold", 0.05),
        late_arrival_window=config.get("late_arrival_window", "24h"),
        duplicate_window=config.get("duplicate_window", "30m"),
        fields=config.get("fields", {}),
        extra=config,
    )


# ── ude pipeline enable ───────────────────────────────────────────────────────

@app.command(name="enable")
def enable(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to enable"),
) -> None:
    """Resume a paused pipeline."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.pipeline import PipelineClient
    PipelineClient(ude_ctx.config).set_enabled(pipeline_id, enabled=True)
    print_success(f"Pipeline '{pipeline_id}' enabled.")


# ── ude pipeline disable ──────────────────────────────────────────────────────

@app.command(name="disable")
def disable(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to disable"),
) -> None:
    """Pause a pipeline without deleting its config or data."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.pipeline import PipelineClient
    confirm = typer.confirm(f"Pause pipeline '{pipeline_id}'?", default=True)
    if not confirm:
        print_info("Aborted.")
        raise typer.Exit()

    PipelineClient(ude_ctx.config).set_enabled(pipeline_id, enabled=False)
    print_warning(f"Pipeline '{pipeline_id}' paused.")
    print_info(f"Resume with: ude pipeline enable {pipeline_id}")


# ── ude pipeline delete ───────────────────────────────────────────────────────

@app.command(name="delete")
def delete(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to deregister"),
) -> None:
    """
    Deregister a pipeline — removes from engine registry and filesystem.
    Pipeline data in BigQuery is NOT deleted.
    """
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    console.print()
    print_warning(f"This will deregister pipeline '{pipeline_id}'.")
    console.print("  Pipeline data in BigQuery will NOT be deleted.")
    console.print()

    confirm = typer.confirm("Are you sure?", default=False)
    if not confirm:
        print_info("Aborted.")
        raise typer.Exit()

    from cli.client.pipeline import PipelineClient
    PipelineClient(ude_ctx.config).deregister(pipeline_id)
    print_success(f"Pipeline '{pipeline_id}' deregistered.")


# ── Shared registration helper ────────────────────────────────────────────────

def _register_with_engine(
    ude_ctx: UDEContext,
    pipeline_id: str,
    natural_key: str,
    scd_type: int,
    subscription_id: str,
    null_threshold: float,
    late_arrival_window: str,
    duplicate_window: str,
    fields: dict,
    extra: dict | None = None,
) -> None:
    """Call POST /pipeline/ and display the result."""
    from cli.client.pipeline import PipelineClient
    from cli.core.errors import APIError

    payload = {
        "pipeline_id":         pipeline_id,
        "natural_key":         natural_key,
        "scd_type":            scd_type,
        "subscription_id":     subscription_id,
        "null_threshold":      null_threshold,
        "late_arrival_window": late_arrival_window,
        "duplicate_window":    duplicate_window,
        "fields":              fields,
    }
    if extra:
        payload["dbt"] = extra.get("dbt", {})

    try:
        result = PipelineClient(ude_ctx.config).register(payload)
        print_success(f"Pipeline '{pipeline_id}' registered with engine.")
        print_info("Engine picks it up on next batch cycle — no restart needed.")
        console.print(f"    Registered at: [muted]{result.get('registered_at', '—')}[/muted]")
    except APIError as exc:
        if exc.status_code == 409:
            print_warning(f"Pipeline '{pipeline_id}' already registered with engine.")
        else:
            print_error(f"Failed to register with engine: {exc}")
            print_info("You can retry later with: ude pipeline register " + pipeline_id)