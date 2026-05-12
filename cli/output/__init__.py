# cli/output/__init__.py
"""
Output layer for the ude CLI.

"""

from cli.output.console import (
    console,
    err_console,
    print_error,
    print_info,
    print_success,
    print_warning,
)
from cli.output.live   import build_watch_layout
from cli.output.panels import (
    dbt_test_results_panel,
    error_panel,
    pipeline_detail_panel,
    pipeline_fields_panel,
    pipeline_last_batch_panel,
    quarantine_detail_panel,
    schema_changes_panel,
    schema_diff_panel,
    stack_status_panel,
)
from cli.output.tables import (
    batch_history_table,
    dbt_status_table,
    metrics_table,
    pipeline_list_table,
    quarantine_list_table,
    schema_history_table,
)

__all__ = [
    # console
    "console",
    "err_console",
    "print_success",
    "print_error",
    "print_warning",
    "print_info",
    # tables
    "pipeline_list_table",
    "quarantine_list_table",
    "schema_history_table",
    "dbt_status_table",
    "metrics_table",
    "batch_history_table",
    # panels
    "stack_status_panel",
    "pipeline_detail_panel",
    "pipeline_fields_panel",
    "pipeline_last_batch_panel",
    "schema_diff_panel",
    "schema_changes_panel",
    "dbt_test_results_panel",
    "quarantine_detail_panel",
    "error_panel",
    # live
    "build_watch_layout",
]