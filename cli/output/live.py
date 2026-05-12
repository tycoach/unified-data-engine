# cli/output/live.py
"""
Rich Live display builders for ude observe watch.

ude observe watch takes over the full terminal (screen=True) and
refreshes a live layout every N seconds. This module owns the layout
structure and rendering logic — cli/commands/observe.py owns the
polling loop and data fetching.

The layout has three sections:
  ┌─────────────────────────────────────┐
  │  Header — pipeline filter + clock   │
  ├─────────────────────────────────────┤
  │  Batch table — last 20 cycles       │
  ├─────────────────────────────────────┤
  │  Footer — totals + alert counters   │
  └─────────────────────────────────────┘

Functions:
    build_watch_layout()    — assemble the full Layout from batch history
    build_header()          — top panel (pipeline name + timestamp)
    build_batch_section()   — scrolling batch history table
    build_footer()          — summary totals row
"""

from __future__ import annotations

import time

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table

from cli.output.tables import batch_history_table


# ── Public entry point ────────────────────────────────────────────────────────

def build_watch_layout(
    batch_history: list[dict],
    pipeline_id: str | None,
    interval: int,
) -> Layout:
    """
    Assemble the full terminal layout for ude observe watch.
    """
    layout = Layout()
    layout.split_column(
        Layout(name="header",  size=3),
        Layout(name="batches", minimum_size=10),
        Layout(name="footer",  size=3),
    )

    layout["header"].update(build_header(pipeline_id, interval))
    layout["batches"].update(build_batch_section(batch_history))
    layout["footer"].update(build_footer(batch_history))

    return layout


# ── Section builders ──────────────────────────────────────────────────────────

def build_header(pipeline_id: str | None, interval: int) -> Panel:
    """
    Top panel — shows pipeline filter, refresh interval, and wall clock.
    """
    pipeline_label = (
        f"[pipeline]{pipeline_id}[/pipeline]"
        if pipeline_id
        else "[muted]all pipelines[/muted]"
    )
    clock = time.strftime("%H:%M:%S")

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(justify="right")

    grid.add_row(
        f"[bold]UDE Watch[/bold]  {pipeline_label}  "
        f"[muted]· refreshing every {interval}s[/muted]",
        f"[muted]{clock}[/muted]",
    )

    return Panel(grid, border_style="cyan", padding=(0, 1))


def build_batch_section(batch_history: list[dict]) -> Panel:
    """
    Main section — scrolling table of the last 20 batch cycles.

    Newest entries are at the bottom. Empty state shows a waiting message.

    """
    visible = batch_history[-20:]  # cap at 20 rows

    if not visible:
        empty_grid = Table.grid(expand=True)
        empty_grid.add_column(justify="center")
        empty_grid.add_row(
            "[muted]Waiting for batch cycles…[/muted]"
        )
        return Panel(
            empty_grid,
            title="[bold]Batch cycles[/bold]",
            border_style="dim",
            padding=(1, 2),
        )

    table = batch_history_table(visible)

    return Panel(
        table,
        title=f"[bold]Batch cycles[/bold] [muted]({len(batch_history)} total)[/muted]",
        border_style="dim",
        padding=(0, 1),
    )


def build_footer(batch_history: list[dict]) -> Panel:
    """
    Footer — aggregate totals and alert counters across all visible cycles.

    Quarantine rate and dbt failure count are highlighted if non-zero.
    """
    total_records     = sum(b.get("records_clean", 0)       for b in batch_history)
    total_quarantined = sum(b.get("records_quarantined", 0)  for b in batch_history)
    total_snaps       = sum(b.get("snapshot_opened", 0)      for b in batch_history)
    dbt_failures      = sum(1 for b in batch_history if not b.get("dbt_passed", True))
    broken_schemas    = sum(1 for b in batch_history if b.get("schema_status") == "BROKEN")
    cycles            = len(batch_history)

    # Colour thresholds
    q_style = (
        "error"   if total_quarantined > 0 and (total_quarantined / max(total_records, 1)) > 0.1
        else "warning" if total_quarantined > 0
        else "success"
    )
    dbt_style    = "error"   if dbt_failures  else "success"
    schema_style = "error"   if broken_schemas else "success"

    grid = Table.grid(expand=True, padding=(0, 3))
    grid.add_column()
    grid.add_column()
    grid.add_column()
    grid.add_column()
    grid.add_column()
    grid.add_column(justify="right", style="muted")

    grid.add_row(
        f"[muted]Cycles:[/muted] [bold]{cycles}[/bold]",
        f"[muted]Records:[/muted] [bold]{total_records:,}[/bold]",
        f"[muted]Quarantined:[/muted] [{q_style}]{total_quarantined:,}[/{q_style}]",
        f"[muted]Snapshots ↑:[/muted] [bold]{total_snaps:,}[/bold]",
        f"[muted]dbt fails:[/muted] [{dbt_style}]{dbt_failures}[/{dbt_style}]",
        f"[muted]BROKEN schemas:[/muted] [{schema_style}]{broken_schemas}[/{schema_style}]",
    )

    return Panel(grid, border_style="dim", padding=(0, 1))


# ── Spinner helper ────────────────────────────────────────────────────────────

def spinning_chars() -> list[str]:
    """
    Returns the character set for a simple CLI spinner.
    Rotate through these on each refresh tick.

    """
    return ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]