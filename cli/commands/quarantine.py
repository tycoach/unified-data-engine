# cli/commands/quarantine.py
"""
ude quarantine — quarantine management commands.

Quarantined batches are records the edge case gate or schema checker
rejected before they could reach dbt. Operators review them here and
decide to approve (release for replay) or reject (discard permanently).

Commands:
    ude quarantine list              — list all quarantined batches
    ude quarantine inspect <id>      — show full batch detail + failure reason
    ude quarantine approve <id>      — release batch for replay on next cycle
    ude quarantine reject  <id>      — discard batch permanently
    ude quarantine replay  <id>      — force immediate replay of a released batch
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from cli.core.checks import assert_stack_running
from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Quarantine management — list, inspect, approve, reject, replay")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude quarantine list ───────────────────────────────────────────────────────

@app.command(name="list")
def list_quarantine(
    ctx: typer.Context,
    pipeline_id: Optional[str] = typer.Option(
        None, "--pipeline", "-p",
        help="Filter by pipeline ID"
    ),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r",
        help="Filter by failure reason (SCHEMA_BROKEN, NULL_THRESHOLD, DUPLICATE, LATE_ARRIVAL)"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max batches to show"),
) -> None:
    """List quarantined batches — newest first."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.quarantine import QuarantineClient
    client = QuarantineClient(ude_ctx.config)
    batches = client.list(pipeline_id=pipeline_id, reason=reason, limit=limit)

    if not batches:
        print_info("No quarantined batches." + (
            f" (filter: pipeline={pipeline_id})" if pipeline_id else ""
        ))
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Batch ID",      style="batch", max_width=24)
    table.add_column("Pipeline",      style="pipeline")
    table.add_column("Failure reason")
    table.add_column("Records",       justify="right")
    table.add_column("Quarantined at", style="muted")
    table.add_column("Status")

    for b in batches:
        reason_str = b.get("failure_reason", "—")
        reason_style = {
            "SCHEMA_BROKEN":   "[error]SCHEMA_BROKEN[/error]",
            "NULL_THRESHOLD":  "[warning]NULL_THRESHOLD[/warning]",
            "DUPLICATE":       "[warning]DUPLICATE[/warning]",
            "LATE_ARRIVAL":    "[muted]LATE_ARRIVAL[/muted]",
            "DBT_TEST_FAILED": "[error]DBT_TEST_FAILED[/error]",
        }.get(reason_str, reason_str)

        status = b.get("status", "pending")
        status_style = {
            "pending":  "[warning]pending[/warning]",
            "approved": "[success]approved[/success]",
            "rejected": "[error]rejected[/error]",
            "replayed": "[info]replayed[/info]",
        }.get(status, status)

        table.add_row(
            b.get("batch_id", "—")[:22],
            b.get("pipeline_id", "—"),
            reason_style,
            str(b.get("record_count", "—")),
            b.get("quarantined_at", "—"),
            status_style,
        )

    console.print()
    console.print(Panel(
        table,
        title=f"[bold]Quarantine[/bold] ({len(batches)} batch{'es' if len(batches) != 1 else ''})",
        border_style="yellow",
        padding=(1, 2),
    ))
    console.print()


# ── ude quarantine inspect ────────────────────────────────────────────────────

@app.command(name="inspect")
def inspect(
    ctx: typer.Context,
    batch_id: str = typer.Argument(..., help="Batch ID to inspect"),
    show_records: bool = typer.Option(
        False, "--records",
        help="Show a sample of the raw records in the batch"
    ),
) -> None:
    """Show full detail for a quarantined batch — failure reason, schema diff, sample records."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.quarantine import QuarantineClient
    client = QuarantineClient(ude_ctx.config)
    batch = client.get(batch_id)

    if not batch:
        print_error(f"Batch '{batch_id}' not found in quarantine.")
        raise typer.Exit(code=1)

    # Summary
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="muted", min_width=22)
    summary.add_column()

    reason = batch.get("failure_reason", "—")
    reason_style = {
        "SCHEMA_BROKEN":   "[error]SCHEMA_BROKEN[/error]",
        "NULL_THRESHOLD":  "[warning]NULL_THRESHOLD[/warning]",
        "DUPLICATE":       "[warning]DUPLICATE[/warning]",
        "LATE_ARRIVAL":    "[muted]LATE_ARRIVAL[/muted]",
        "DBT_TEST_FAILED": "[error]DBT_TEST_FAILED[/error]",
    }.get(reason, reason)

    rows = [
        ("Batch ID",        batch.get("batch_id", "—")),
        ("Pipeline",        batch.get("pipeline_id", "—")),
        ("Failure reason",  reason_style),
        ("Record count",    str(batch.get("record_count", "—"))),
        ("Quarantined at",  batch.get("quarantined_at", "—")),
        ("Status",          batch.get("status", "—")),
        ("Kafka offset",    str(batch.get("kafka_offset", "—"))),
    ]
    for label, value in rows:
        summary.add_row(label, value)

    console.print()
    console.print(Panel(
        summary,
        title=f"[bold]Quarantine batch[/bold] · [batch]{batch_id[:22]}[/batch]",
        border_style="yellow",
        padding=(1, 2),
    ))

    # Schema diff (if SCHEMA_BROKEN)
    schema_diff = batch.get("schema_diff", {})
    if schema_diff:
        diff_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        diff_table.add_column("Field")
        diff_table.add_column("Change")

        for field, change in schema_diff.get("removed", {}).items():
            diff_table.add_row(field, "[error]removed[/error]")
        for field, change in schema_diff.get("added", {}).items():
            diff_table.add_row(field, "[success]added[/success]")
        for field, detail in schema_diff.get("type_changed", {}).items():
            diff_table.add_row(field, f"[warning]{detail.get('from')} → {detail.get('to')}[/warning]")

        console.print(Panel(
            diff_table,
            title="Schema diff",
            border_style="dim",
            padding=(1, 2),
        ))

    # Sample records
    if show_records:
        records = batch.get("sample_records", [])
        if records:
            print_info(f"Sample records (showing {len(records)}):")
            import json
            console.print_json(json.dumps(records, indent=2, default=str))
        else:
            print_info("No sample records available.")

    console.print()
    console.print("  Actions:")
    console.print(f"  [bold]ude quarantine approve {batch_id}[/bold]  — release for replay")
    console.print(f"  [bold]ude quarantine reject  {batch_id}[/bold]  — discard permanently")
    console.print()


# ── ude quarantine approve ────────────────────────────────────────────────────

@app.command(name="approve")
def approve(
    ctx: typer.Context,
    batch_id: str = typer.Argument(..., help="Batch ID to release for replay"),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r",
        help="Reason for approval (stored in audit log)"
    ),
) -> None:
    """Release a quarantined batch for replay on the next engine cycle."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.quarantine import QuarantineClient
    client = QuarantineClient(ude_ctx.config)

    approval_reason = reason or typer.prompt(
        "Reason",
        default="Reviewed and approved by operator",
    )

    confirm = typer.confirm(f"Release batch '{batch_id[:22]}' for replay?", default=False)
    if not confirm:
        print_info("Aborted.")
        raise typer.Exit()

    client.approve(batch_id, reason=approval_reason)
    print_success(f"Batch '{batch_id[:22]}' approved — will replay on next engine cycle.")
    print_info("Force immediate replay: ude quarantine replay " + batch_id)


# ── ude quarantine reject ─────────────────────────────────────────────────────

@app.command(name="reject")
def reject(
    ctx: typer.Context,
    batch_id: str = typer.Argument(..., help="Batch ID to discard"),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r",
        help="Reason for rejection (stored in audit log)"
    ),
) -> None:
    """Permanently discard a quarantined batch."""
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.quarantine import QuarantineClient
    client = QuarantineClient(ude_ctx.config)

    rejection_reason = reason or typer.prompt(
        "Reason",
        default="Bad data — discarded by operator",
    )

    console.print()
    print_warning(f"This will permanently discard batch '{batch_id[:22]}'.")
    confirm = typer.confirm("Are you sure?", default=False)
    if not confirm:
        print_info("Aborted.")
        raise typer.Exit()

    client.reject(batch_id, reason=rejection_reason)
    print_success(f"Batch '{batch_id[:22]}' rejected and discarded.")


# ── ude quarantine replay ─────────────────────────────────────────────────────

@app.command(name="replay")
def replay(
    ctx: typer.Context,
    batch_id: str = typer.Argument(..., help="Batch ID to replay immediately"),
) -> None:
    """
    Force immediate replay of an approved quarantine batch.

    The batch must already be in 'approved' status.
    Use 'ude quarantine approve' first if it's still pending.
    """
    ude_ctx = _ctx(ctx)
    assert_stack_running(ude_ctx.config)

    from cli.client.quarantine import QuarantineClient
    client = QuarantineClient(ude_ctx.config)

    result = client.replay(batch_id)
    status = result.get("status", "unknown")

    if status == "replaying":
        print_success(f"Replay triggered for batch '{batch_id[:22]}'.")
        print_info("Monitor progress: ude observe watch")
    elif status == "not_approved":
        print_error("Batch is not in 'approved' status. Run:")
        console.print(f"  [bold]ude quarantine approve {batch_id}[/bold]")
        raise typer.Exit(code=1)
    else:
        print_warning(f"Unexpected status: {status}")