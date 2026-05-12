# cli/output/tables.py
"""
Rich table builders for the ude CLI.

Every command that renders a list uses a function from here.
Command files call these and pass the result to console.print() —
they never build Table objects directly.


"""

from __future__ import annotations

from rich.table import Table


# ── Pipeline list ─────────────────────────────────────────────────────────────

def pipeline_list_table(pipelines: list[dict]) -> Table:
    """
    Render a summary row per pipeline.
    """
    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("Pipeline ID",   style="pipeline",  min_width=14)
    table.add_column("SCD",           justify="center",  min_width=6)
    table.add_column("Status",        min_width=12)
    table.add_column("Schema ver",    justify="center",  min_width=10)
    table.add_column("Last batch",    style="muted",     min_width=20)
    table.add_column("Records",       justify="right",   min_width=8)

    for p in pipelines:
        status_str = (
            "[success]● active[/success]"
            if p.get("enabled", True)
            else "[warning]○ paused[/warning]"
        )
        records = p.get("last_batch_records")
        table.add_row(
            p.get("pipeline_id", "—"),
            f"Type {p.get('scd_type', '?')}",
            status_str,
            str(p.get("schema_version", "—")),
            p.get("last_batch_at", "—"),
            f"{records:,}" if isinstance(records, int) else "—",
        )

    return table


# ── Quarantine list ───────────────────────────────────────────────────────────

def quarantine_list_table(batches: list[dict]) -> Table:
    """
    Render a summary row per quarantined batch.

    """
    _REASON_STYLE = {
        "SCHEMA_BROKEN":   "[error]SCHEMA_BROKEN[/error]",
        "NULL_THRESHOLD":  "[warning]NULL_THRESHOLD[/warning]",
        "DUPLICATE":       "[warning]DUPLICATE[/warning]",
        "LATE_ARRIVAL":    "[muted]LATE_ARRIVAL[/muted]",
        "DBT_TEST_FAILED": "[error]DBT_TEST_FAILED[/error]",
    }
    _STATUS_STYLE = {
        "pending":  "[warning]pending[/warning]",
        "approved": "[success]approved[/success]",
        "rejected": "[error]rejected[/error]",
        "replayed": "[info]replayed[/info]",
    }

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("Batch ID",       style="batch",   max_width=24)
    table.add_column("Pipeline",       style="pipeline",min_width=12)
    table.add_column("Failure reason",                  min_width=18)
    table.add_column("Records",        justify="right", min_width=8)
    table.add_column("Quarantined at", style="muted",   min_width=20)
    table.add_column("Status",                          min_width=10)

    for b in batches:
        reason = b.get("failure_reason", "—")
        status = b.get("status", "pending")
        count  = b.get("record_count")

        table.add_row(
            b.get("batch_id", "—")[:22],
            b.get("pipeline_id", "—"),
            _REASON_STYLE.get(reason, reason),
            f"{count:,}" if isinstance(count, int) else "—",
            b.get("quarantined_at", "—"),
            _STATUS_STYLE.get(status, status),
        )

    return table


# ── Schema history ────────────────────────────────────────────────────────────

def schema_history_table(versions: list[dict]) -> Table:
    """
    Render one row per schema version.
    """
    _CHANGE_STYLE = {
        "INITIAL": "[info]INITIAL[/info]",
        "EVOLVED": "[success]EVOLVED[/success]",
        "BROKEN":  "[error]BROKEN[/error]",
    }

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("Version",        justify="right", min_width=8)
    table.add_column("Locked at",      style="muted",   min_width=22)
    table.add_column("Change",                          min_width=10)
    table.add_column("Fields added",                    min_width=16)
    table.add_column("Fields removed",                  min_width=16)
    table.add_column("Approved by",    style="muted",   min_width=12)

    for v in versions:
        change = v.get("change_type", "INITIAL")
        added   = v.get("fields_added", [])
        removed = v.get("fields_removed", [])

        table.add_row(
            str(v.get("version", "—")),
            v.get("locked_at", "—"),
            _CHANGE_STYLE.get(change, change),
            ", ".join(added)   if added   else "[muted]—[/muted]",
            ", ".join(removed) if removed else "[muted]—[/muted]",
            v.get("approved_by", "engine"),
        )

    return table


# ── dbt run status ────────────────────────────────────────────────────────────

def dbt_status_table(runs: list[dict]) -> Table:
    """
    Render one row per pipeline's last dbt run.
    """
    _STATUS_STYLE = {
        "success": "[success]✓ success[/success]",
        "failed":  "[error]✗ failed[/error]",
        "running": "[info]⟳ running[/info]",
    }

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("Pipeline",     style="pipeline", min_width=14)
    table.add_column("Last run at",  style="muted",    min_width=22)
    table.add_column("Status",                         min_width=12)
    table.add_column("Duration",     justify="right",  min_width=10)
    table.add_column("Tests ✓",      justify="right",  min_width=8)
    table.add_column("Tests ✗",      justify="right",  min_width=8)
    table.add_column("Rows",         justify="right",  min_width=8)

    for r in runs:
        status   = r.get("status", "—")
        failures = r.get("tests_failed", 0)
        dur_ms   = r.get("duration_ms")
        rows     = r.get("rows_affected")

        table.add_row(
            r.get("pipeline_id", "—"),
            r.get("last_run_at", "—"),
            _STATUS_STYLE.get(status, status),
            f"{dur_ms:,}ms" if isinstance(dur_ms, int) else "—",
            str(r.get("tests_passed", "—")),
            f"[error]{failures}[/error]" if failures else "0",
            f"{rows:,}"     if isinstance(rows, int)  else "—",
        )

    return table


# ── Prometheus metrics ────────────────────────────────────────────────────────

def metrics_table(metrics: list[dict]) -> Table:
    """
    Render one row per Prometheus metric.
    """
    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
        expand=True,
    )
    table.add_column("Metric",   style="muted",    min_width=42)
    table.add_column("Pipeline", style="pipeline", min_width=14)
    table.add_column("Value",    justify="right",  min_width=10)
    table.add_column("Labels",   style="dim",      min_width=20)

    for m in metrics:
        value = m.get("value")
        table.add_row(
            m.get("name", "—"),
            m.get("pipeline", "—"),
            f"{value:,.2f}" if isinstance(value, float) else str(value) if value is not None else "—",
            m.get("labels", ""),
        )

    return table


# ── Batch history (observe watch) ─────────────────────────────────────────────

def batch_history_table(batches: list[dict]) -> Table:
    """
    Render one row per recent batch cycle for ude observe watch.
    """
    _SCHEMA_STYLE = {
        "MATCH":   "[success]MATCH[/success]",
        "EVOLVED": "[warning]EVOLVED[/warning]",
        "BROKEN":  "[error]BROKEN[/error]",
    }

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 2),
        expand=True,
    )
    table.add_column("Time",         style="muted",  min_width=10)
    table.add_column("Pipeline",     style="pipeline",min_width=12)
    table.add_column("Records",      justify="right", min_width=8)
    table.add_column("Quarantined",  justify="right", min_width=12)
    table.add_column("dbt",          justify="center",min_width=5)
    table.add_column("Snaps ↑",      justify="right", min_width=8)
    table.add_column("Schema",                        min_width=10)
    table.add_column("Duration",     justify="right", min_width=10, style="muted")

    for b in batches:
        qrate    = b.get("quarantine_rate", 0.0)
        dbt_ok   = b.get("dbt_passed", True)
        schema   = b.get("schema_status", "MATCH")
        dur_ms   = b.get("duration_ms")
        records  = b.get("records_clean")
        snaps    = b.get("snapshot_opened")

        q_str = (
            f"[error]{qrate:.1%}[/error]"   if qrate > 0.10
            else f"[warning]{qrate:.1%}[/warning]" if qrate > 0
            else "[success]0%[/success]"
        )

        table.add_row(
            b.get("batch_time", "—"),
            b.get("pipeline_id", "—"),
            f"{records:,}" if isinstance(records, int) else "—",
            q_str,
            "[success]✓[/success]" if dbt_ok else "[error]✗[/error]",
            str(snaps) if snaps is not None else "—",
            _SCHEMA_STYLE.get(schema, schema),
            f"{dur_ms:,}ms" if isinstance(dur_ms, int) else "—",
        )

    return table