# cli/commands/schema.py
"""
ude schema — schema registry operations.

Commands:
    ude schema sync              — regenerate dbt source contracts from registry
    ude schema history <id>      — show version timeline for a pipeline's schema
    ude schema diff   <id>       — compare locked schema vs what's arriving live
    ude schema approve <id>      — approve a BROKEN migration and unblock the pipeline
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from cli.core.checks import assert_project_exists, assert_stack_running
from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Schema operations — show, sync, history, diff, approve")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude schema sync ───────────────────────────────────────────────────────────

@app.command(name="sync")
def sync(
    ctx: typer.Context,
    pipeline_id: Optional[str] = typer.Option(
        None, "--pipeline", "-p",
        help="Sync only a specific pipeline. Syncs all if not provided."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show what would change without writing files."
    ),
) -> None:
    """
    Regenerate dbt/models/staging/_sources.yml from the schema registry.

    Keeps dbt source contracts permanently in sync with what the engine
    has locked. Run this after any schema approval or manual registry edit.
    """
    assert_project_exists()
    assert_stack_running(_ctx(ctx).config)

    from cli.client.schema import SchemaClient
    client = SchemaClient(_ctx(ctx).config)

    target = pipeline_id or "all pipelines"
    action = "Would update" if dry_run else "Syncing"
    print_info(f"{action} dbt contracts for {target}...")

    result = client.sync(pipeline_id=pipeline_id, dry_run=dry_run)

    updated   = result.get("updated", [])
    unchanged = result.get("unchanged", [])

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Pipeline")
    table.add_column("Result")
    table.add_column("Schema version", justify="right")

    for item in updated:
        label = "[warning]would update[/warning]" if dry_run else "[success]updated[/success]"
        table.add_row(item["pipeline_id"], label, str(item.get("version", "—")))

    for item in unchanged:
        table.add_row(item["pipeline_id"], "[muted]unchanged[/muted]", str(item.get("version", "—")))

    console.print()
    console.print(Panel(
        table,
        title="[bold]Schema sync[/bold]" + (" [warning](dry run)[/warning]" if dry_run else ""),
        border_style="blue",
        padding=(1, 2),
    ))

    if not dry_run and updated:
        print_success(f"{len(updated)} contract(s) updated → dbt/models/staging/_sources.yml")
    elif not updated:
        print_info("All contracts already up to date.")
    console.print()


# ── ude schema history ────────────────────────────────────────────────────────

@app.command(name="history")
def history(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to show schema history for"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of versions to show"),
) -> None:
    """Show the schema version timeline for a pipeline."""
    assert_stack_running(_ctx(ctx).config)

    from cli.client.schema import SchemaClient
    client = SchemaClient(_ctx(ctx).config)
    versions = client.history(pipeline_id, limit=limit)

    if not versions:
        print_warning(f"No schema history found for '{pipeline_id}'.")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Version",    justify="right")
    table.add_column("Locked at", style="muted")
    table.add_column("Change type")
    table.add_column("Fields added")
    table.add_column("Fields removed")
    table.add_column("Approved by", style="muted")

    for v in versions:
        change = v.get("change_type", "INITIAL")
        change_style = {
            "INITIAL":  "[info]INITIAL[/info]",
            "EVOLVED":  "[success]EVOLVED[/success]",
            "BROKEN":   "[error]BROKEN[/error]",
        }.get(change, change)

        table.add_row(
            str(v.get("version", "—")),
            v.get("locked_at", "—"),
            change_style,
            ", ".join(v.get("fields_added", [])) or "—",
            ", ".join(v.get("fields_removed", [])) or "—",
            v.get("approved_by", "engine"),
        )

    console.print()
    console.print(Panel(
        table,
        title=f"[bold]Schema history[/bold] · [pipeline]{pipeline_id}[/pipeline]",
        border_style="blue",
        padding=(1, 2),
    ))
    console.print()


# ── ude schema diff ───────────────────────────────────────────────────────────

@app.command(name="diff")
def diff(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to diff"),
) -> None:
    """
    Compare the locked schema against what's arriving live from Pub/Sub.

    Shows added columns, removed columns, and type changes so operators
    can decide whether to approve a migration before a BROKEN batch lands.
    """
    assert_stack_running(_ctx(ctx).config)

    from cli.client.schema import SchemaClient
    client = SchemaClient(_ctx(ctx).config)
    diff_result = client.diff(pipeline_id)

    deviation = diff_result.get("deviation", "MATCH")
    locked_v  = diff_result.get("locked_version", "—")
    live_v    = diff_result.get("live_version", "—")

    deviation_style = {
        "MATCH":   "[success]MATCH[/success]",
        "EVOLVED": "[warning]EVOLVED[/warning]",
        "BROKEN":  "[error]BROKEN[/error]",
    }.get(deviation, deviation)

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="muted", min_width=18)
    summary.add_column()
    summary.add_row("Deviation",      deviation_style)
    summary.add_row("Locked version", str(locked_v))
    summary.add_row("Live version",   str(live_v))

    console.print()
    console.print(Panel(
        summary,
        title=f"[bold]Schema diff[/bold] · [pipeline]{pipeline_id}[/pipeline]",
        border_style={
            "MATCH": "green", "EVOLVED": "yellow", "BROKEN": "red"
        }.get(deviation, "cyan"),
        padding=(1, 2),
    ))

    changes = diff_result.get("changes", [])
    if changes:
        change_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        change_table.add_column("Field")
        change_table.add_column("Change")
        change_table.add_column("Locked type")
        change_table.add_column("Live type")

        for c in changes:
            change_type = c.get("change", "—")
            style = {
                "added":   "[success]added[/success]",
                "removed": "[error]removed[/error]",
                "widened": "[warning]widened[/warning]",
                "incompatible": "[error]incompatible[/error]",
            }.get(change_type, change_type)

            change_table.add_row(
                c.get("field", "—"),
                style,
                c.get("locked_type", "—"),
                c.get("live_type", "—"),
            )

        console.print(Panel(
            change_table,
            title="Field-level changes",
            border_style="dim",
            padding=(1, 2),
        ))

    if deviation == "BROKEN":
        console.print()
        print_warning("Pipeline is blocked. Review and approve migration:")
        console.print(f"  [bold]ude schema approve {pipeline_id}[/bold]")
    elif deviation == "EVOLVED":
        print_info("Schema evolved — engine will auto-update the contract on next batch.")

    console.print()


# ── ude schema approve ────────────────────────────────────────────────────────

@app.command(name="approve")
def approve(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to approve migration for"),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r",
        help="Reason for approval (stored in audit log)"
    ),
) -> None:
    """
    Approve a BROKEN schema migration and unblock the quarantined pipeline.

    This updates the locked schema to the new version, regenerates the
    dbt source contract, and releases the quarantined batch for replay.
    """
    assert_stack_running(_ctx(ctx).config)

    from cli.client.schema import SchemaClient
    client = SchemaClient(_ctx(ctx).config)

    # Show current diff before asking for confirmation
    diff_result = client.diff(pipeline_id)
    deviation   = diff_result.get("deviation", "MATCH")

    if deviation == "MATCH":
        print_info(f"Pipeline '{pipeline_id}' schema is at MATCH — no migration to approve.")
        raise typer.Exit()

    if deviation != "BROKEN":
        print_info(f"Deviation is {deviation}, not BROKEN. No operator approval required.")
        raise typer.Exit()

    changes = diff_result.get("changes", [])
    console.print()
    print_warning(f"Approving BROKEN migration for '{pipeline_id}'.")
    console.print(f"  Changes: {len(changes)} field(s) affected")
    for c in changes:
        console.print(f"    [muted]·[/muted] {c.get('field')}: {c.get('change')}")
    console.print()

    approval_reason = reason or typer.prompt(
        "Reason for approval (stored in audit log)",
        default="Upstream schema change approved by operator",
    )

    confirm = typer.confirm("Confirm approval?", default=False)
    if not confirm:
        print_info("Aborted. Pipeline remains blocked.")
        raise typer.Exit()

    result = client.approve_migration(pipeline_id, reason=approval_reason)

    print_success(f"Migration approved. Schema updated to v{result.get('new_version', '?')}.")
    print_info("dbt contract regenerated → dbt/models/staging/_sources.yml")
    print_info("Quarantined batches released for replay on next cycle.")
    console.print()

# ── ude schema show ───────────────────────────────────────────────────────────

@app.command(name="show")
def show(
    ctx: typer.Context,
    pipeline_id: str = typer.Argument(..., help="Pipeline ID to inspect schema for"),
) -> None:
    """
    Show the locked schema for a pipeline — field names, types, and constraints.

    Use this to inspect what schema the engine has locked before sending
    data or after registering a new pipeline.
    """
    assert_stack_running(_ctx(ctx).config)

    from cli.client.schema import SchemaClient
    from cli.client.http import UDEHttpClient
    from cli.core.errors import APIError
    client = SchemaClient(_ctx(ctx).config)

    try:
        schema = UDEHttpClient.get(client, f"/schema/{pipeline_id}")
    except APIError as exc:
        if exc.status_code == 404:
            print_warning(f"No locked schema for '{pipeline_id}' yet.")
            print_info("The schema is locked on the pipeline's first batch.")
            print_info("Seed data with: make seed")
            raise typer.Exit()
        raise

    if not schema:
        print_warning(f"No locked schema for '{pipeline_id}' yet.")
        raise typer.Exit()

    fields    = schema.get("fields", {})
    version   = schema.get("version", "—")
    locked_at = schema.get("locked_at", "—")

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="muted", min_width=16)
    summary.add_column(style="bold")
    summary.add_row("Pipeline",  pipeline_id)
    summary.add_row("Version",   f"v{version}")
    summary.add_row("Locked at", locked_at)
    summary.add_row("Fields",    str(len(fields)))

    console.print()
    console.print(Panel(
        summary,
        title=f"[pipeline]{pipeline_id}[/pipeline] · locked schema",
        border_style="blue",
        padding=(1, 2),
    ))

    if fields:
        field_table = Table(
            show_header=True, header_style="bold",
            box=None, padding=(0, 2),
        )
        field_table.add_column("Field",    min_width=20)
        field_table.add_column("Type",     min_width=12)
        field_table.add_column("Nullable", justify="center", min_width=10)

        for fname, fmeta in fields.items():
            if isinstance(fmeta, dict):
                ftype    = fmeta.get("type", "—")
                nullable = fmeta.get("nullable", True)
            else:
                ftype    = str(fmeta)
                nullable = True

            nullable_str = "[muted]yes[/muted]" if nullable else "[bold]no[/bold]"
            field_table.add_row(fname, ftype, nullable_str)

        console.print(Panel(
            field_table,
            title=f"[pipeline]{pipeline_id}[/pipeline] · fields",
            border_style="blue",
            padding=(1, 2),
        ))
    else:
        print_warning("No field definitions in locked schema.")

    console.print()
    console.print(
        f"  [muted]Run [bold]ude schema history {pipeline_id}[/bold] "
        f"to see version timeline.[/muted]"
    )
    console.print()
