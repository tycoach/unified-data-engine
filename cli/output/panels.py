# cli/output/panels.py
"""
Rich panel builders for the ude CLI.

Panels are bordered boxes used for detailed single-item views —
stack status, batch summaries, pipeline inspect, schema diff.

Command files call these and pass the result to console.print().
They never build Panel objects directly.

Functions:
    stack_status_panel()       — ude status
    pipeline_detail_panel()    — ude pipeline inspect (config section)
    schema_diff_panel()        — ude schema diff (deviation summary)
    batch_summary_panel()      — ude observe watch (batch cycle detail)
    dbt_test_results_panel()   — dbt test results from run_results.json
    quarantine_detail_panel()  — ude quarantine inspect (batch header)
    error_panel()              — any UDEError rendered to user
"""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table


# ── Stack status ──────────────────────────────────────────────────────────────

def stack_status_panel(components: list[tuple[str, bool, str]], env: str) -> Panel:
    """
    Build the stack health panel for ude status.
    """
    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
    )
    table.add_column("Component", style="label",  min_width=16)
    table.add_column("Status",                    min_width=14)
    table.add_column("Address",   style="muted")

    for name, alive, addr in components:
        status_str = (
            "[success]● running[/success]"
            if alive
            else "[error]○ not running[/error]"
        )
        table.add_row(name, status_str, addr)

    return Panel(
        table,
        title=f"[bold]UDE Status[/bold] · env=[info]{env}[/info]",
        border_style="cyan",
        padding=(1, 2),
    )


# ── Pipeline detail ───────────────────────────────────────────────────────────

def pipeline_detail_panel(pipeline: dict) -> Panel:
    """
    Build the config section panel for ude pipeline inspect.
    """
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", min_width=22)
    grid.add_column(style="bold")

    rows = [
        ("Pipeline ID",      pipeline.get("pipeline_id", "—")),
        ("SCD type",         f"Type {pipeline.get('scd_type', '?')}"),
        ("Subscription",     pipeline.get("subscription_id", "—")),
        ("Natural key",      pipeline.get("natural_key", "—")),
        ("Null threshold",   str(pipeline.get("null_threshold", "—"))),
        ("Late arrival",     pipeline.get("late_arrival_window", "—")),
        ("Duplicate window", pipeline.get("duplicate_window", "—")),
        ("Edge case mode",   pipeline.get("edge_case_mode", "—")),
        ("Schema version",   str(pipeline.get("schema_version", "—"))),
        ("Schema locked at", pipeline.get("schema_locked_at", "—")),
        ("Status",           "active" if pipeline.get("enabled", True) else "paused"),
    ]
    for label, value in rows:
        grid.add_row(label, value)

    pid = pipeline.get("pipeline_id", "pipeline")
    return Panel(
        grid,
        title=f"[pipeline]{pid}[/pipeline] · config",
        border_style="magenta",
        padding=(1, 2),
    )


def pipeline_fields_panel(pipeline: dict) -> Panel | None:
    """
    Build the schema fields panel for ude pipeline inspect.
    Returns None if the pipeline has no fields defined.
    """
    fields = pipeline.get("fields", {})
    if not fields:
        return None

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Field",    min_width=16)
    table.add_column("Type",     min_width=10)
    table.add_column("Nullable", justify="center", min_width=10)

    for fname, fmeta in fields.items():
        nullable = (
            "[muted]yes[/muted]"
            if fmeta.get("nullable")
            else "[bold]no[/bold]"
        )
        table.add_row(fname, fmeta.get("type", "—"), nullable)

    pid = pipeline.get("pipeline_id", "pipeline")
    return Panel(
        table,
        title=f"[pipeline]{pid}[/pipeline] · schema fields",
        border_style="blue",
        padding=(1, 2),
    )


def pipeline_last_batch_panel(pipeline: dict) -> Panel | None:
    """
    Build the last batch stats panel for ude pipeline inspect.
    Returns None if no batch data is present.
    """
    batch = pipeline.get("last_batch", {})
    if not batch:
        return None

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", min_width=22)
    grid.add_column()

    dbt_ok = batch.get("dbt_passed", True)
    rows = [
        ("Batch ID",            batch.get("batch_id", "—")),
        ("Processed at",        batch.get("processed_at", "—")),
        ("Records clean",       str(batch.get("records_clean", "—"))),
        ("Records quarantined", str(batch.get("records_quarantined", "—"))),
        ("dbt run",             "[success]pass[/success]" if dbt_ok else "[error]fail[/error]"),
        ("Snapshot opened",     str(batch.get("snapshot_opened", "—"))),
        ("Snapshot closed",     str(batch.get("snapshot_closed", "—"))),
    ]
    for label, value in rows:
        grid.add_row(label, value)

    pid = pipeline.get("pipeline_id", "pipeline")
    return Panel(
        grid,
        title=f"[pipeline]{pid}[/pipeline] · last batch",
        border_style="cyan",
        padding=(1, 2),
    )


# ── Schema diff ───────────────────────────────────────────────────────────────

def schema_diff_panel(pipeline_id: str, diff: dict) -> Panel:
    """
    Build the schema diff summary panel for ude schema diff.
    """
    deviation     = diff.get("deviation", "MATCH")
    locked_ver    = diff.get("locked_version", "—")
    live_ver      = diff.get("live_version", "—")

    _DEVIATION_STYLE = {
        "MATCH":   "[success]MATCH[/success]",
        "EVOLVED": "[warning]EVOLVED[/warning]",
        "BROKEN":  "[error]BROKEN[/error]",
    }
    _BORDER = {
        "MATCH": "green", "EVOLVED": "yellow", "BROKEN": "red",
    }

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", min_width=18)
    grid.add_column()
    grid.add_row("Deviation",      _DEVIATION_STYLE.get(deviation, deviation))
    grid.add_row("Locked version", str(locked_ver))
    grid.add_row("Live version",   str(live_ver))

    return Panel(
        grid,
        title=f"[bold]Schema diff[/bold] · [pipeline]{pipeline_id}[/pipeline]",
        border_style=_BORDER.get(deviation, "cyan"),
        padding=(1, 2),
    )


def schema_changes_panel(changes: list[dict]) -> Panel:
    """
    Build the field-level changes panel beneath the schema diff summary.

    """
    _CHANGE_STYLE = {
        "added":        "[success]added[/success]",
        "removed":      "[error]removed[/error]",
        "widened":      "[warning]widened[/warning]",
        "incompatible": "[error]incompatible[/error]",
    }

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Field",       min_width=16)
    table.add_column("Change",      min_width=14)
    table.add_column("Locked type", min_width=12)
    table.add_column("Live type",   min_width=12)

    for c in changes:
        change_type = c.get("change", "—")
        table.add_row(
            c.get("field", "—"),
            _CHANGE_STYLE.get(change_type, change_type),
            c.get("locked_type", "—"),
            c.get("live_type",   "—"),
        )

    return Panel(
        table,
        title="Field-level changes",
        border_style="dim",
        padding=(1, 2),
    )


# ── dbt test results ──────────────────────────────────────────────────────────

def dbt_test_results_panel(results: list[dict], pipeline_id: str) -> Panel:
    """
    Build a test results panel from run_results.json content.
    """
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Test",     min_width=40)
    table.add_column("Status",   min_width=10, justify="center")
    table.add_column("Failures", min_width=10, justify="right")
    table.add_column("Message",  min_width=20, style="muted")

    passed = 0
    failed = 0

    for r in results:
        status   = r.get("status", "—")
        failures = r.get("failures", 0)
        name     = r.get("unique_id", "—").split(".")[-1]
        message  = r.get("message") or ""

        if status == "pass":
            status_str = "[success]✓ pass[/success]"
            passed += 1
        elif status == "fail":
            status_str = "[error]✗ fail[/error]"
            failed += 1
        else:
            status_str = f"[muted]{status}[/muted]"

        table.add_row(
            name,
            status_str,
            str(failures) if failures else "—",
            message[:60] + "…" if len(message) > 60 else message,
        )

    summary = f"[success]{passed} passed[/success]"
    if failed:
        summary += f"  [error]{failed} failed[/error]"

    return Panel(
        table,
        title=f"[bold]dbt test results[/bold] · [pipeline]{pipeline_id}[/pipeline] · {summary}",
        border_style="green" if not failed else "red",
        padding=(1, 2),
    )


# ── Quarantine batch detail ───────────────────────────────────────────────────

def quarantine_detail_panel(batch: dict) -> Panel:
    """
    Build the header summary panel for ude quarantine inspect.
    """
    _REASON_STYLE = {
        "SCHEMA_BROKEN":   "[error]SCHEMA_BROKEN[/error]",
        "NULL_THRESHOLD":  "[warning]NULL_THRESHOLD[/warning]",
        "DUPLICATE":       "[warning]DUPLICATE[/warning]",
        "LATE_ARRIVAL":    "[muted]LATE_ARRIVAL[/muted]",
        "DBT_TEST_FAILED": "[error]DBT_TEST_FAILED[/error]",
    }

    reason  = batch.get("failure_reason", "—")
    count   = batch.get("record_count")
    bid     = batch.get("batch_id", "—")

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", min_width=22)
    grid.add_column()

    rows = [
        ("Batch ID",       bid),
        ("Pipeline",       batch.get("pipeline_id", "—")),
        ("Failure reason", _REASON_STYLE.get(reason, reason)),
        ("Record count",   f"{count:,}" if isinstance(count, int) else "—"),
        ("Quarantined at", batch.get("quarantined_at", "—")),
        ("Status",         batch.get("status", "—")),
    ]
    for label, value in rows:
        grid.add_row(label, value)

    return Panel(
        grid,
        title=f"[bold]Quarantine batch[/bold] · [batch]{bid[:24]}[/batch]",
        border_style="yellow",
        padding=(1, 2),
    )


# ── Error panel ───────────────────────────────────────────────────────────────

def error_panel(message: str) -> Panel:
    """
    Build a red error panel for clean UDEError display.
    Used by the top-level error handler in cli/main.py.
    """
    return Panel(
        message,
        title="[error]Error[/error]",
        border_style="red",
        padding=(0, 1),
    )