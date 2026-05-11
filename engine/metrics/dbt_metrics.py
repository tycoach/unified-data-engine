# engine/metrics/dbt_metrics.py
# Prometheus metrics for dbt run health — new in UDE v2
# Tracks: run duration, test failures, rows affected, contract violations

from prometheus_client import Counter, Histogram, Gauge
import logging

logger = logging.getLogger(__name__)

# ── dbt run metrics ───────────────────────────────────────────────────────────

ude_dbt_run_duration_seconds = Histogram(
    "ude_dbt_run_duration_seconds",
    "Time taken for each dbt run step",
    ["pipeline_id", "model_type"],
    buckets=[1, 2, 5, 10, 15, 20, 25, 30, 45, 60],
)

ude_dbt_test_failures_total = Counter(
    "ude_dbt_test_failures_total",
    "Total dbt test failures — each failure blocks checkpoint",
    ["pipeline_id", "test_name", "model"],
)

ude_dbt_model_rows_affected = Gauge(
    "ude_dbt_model_rows_affected",
    "Rows written by each dbt model per run",
    ["pipeline_id", "model"],
)

# ── Snapshot metrics ──────────────────────────────────────────────────────────

ude_snapshot_records_opened = Counter(
    "ude_snapshot_records_opened_total",
    "New snapshot records opened (SCD Type 2 changes detected)",
    ["pipeline_id", "snapshot"],
)

ude_snapshot_records_closed = Counter(
    "ude_snapshot_records_closed_total",
    "Old snapshot records closed per batch",
    ["pipeline_id", "snapshot"],
)

# ── Contract violation metrics ────────────────────────────────────────────────

ude_dbt_contract_violations_total = Counter(
    "ude_dbt_contract_violations_total",
    "dbt source contract violations — means edge case gate has a gap",
    ["pipeline_id", "column"],
)

# ── Package version gauge ─────────────────────────────────────────────────────

ude_dbt_run_status = Gauge(
    "ude_dbt_run_status",
    "Last dbt run status (1=success, 0=failure)",
    ["pipeline_id"],
)


class DbtMetrics:
    """
    Helper class for emitting dbt-specific metrics.
    Called from DbtRunner after each step.
    """

    @staticmethod
    def record_run_duration(pipeline_id: str, model_type: str, duration: float):
        """Record how long a dbt run step took."""
        ude_dbt_run_duration_seconds.labels(
            pipeline_id=pipeline_id,
            model_type=model_type,
        ).observe(duration)

    @staticmethod
    def record_test_failure(pipeline_id: str, test_name: str, model: str):
        """Record a dbt test failure — each failure blocks checkpoint."""
        ude_dbt_test_failures_total.labels(
            pipeline_id=pipeline_id,
            test_name=test_name,
            model=model,
        ).inc()
        logger.warning(
            f"[DbtMetrics] Test failure: {test_name} on {model} "
            f"(pipeline={pipeline_id})"
        )

    @staticmethod
    def record_run_result(pipeline_id: str, success: bool):
        """Record overall dbt run success/failure."""
        ude_dbt_run_status.labels(pipeline_id=pipeline_id).set(
            1 if success else 0
        )

    @staticmethod
    def record_snapshot_changes(
        pipeline_id: str,
        snapshot: str,
        opened: int,
        closed: int,
    ):
        """
        Record SCD Type 2 snapshot changes.
        opened should equal closed — divergence indicates a bug.
        """
        ude_snapshot_records_opened.labels(
            pipeline_id=pipeline_id,
            snapshot=snapshot,
        ).inc(opened)

        ude_snapshot_records_closed.labels(
            pipeline_id=pipeline_id,
            snapshot=snapshot,
        ).inc(closed)

        if opened != closed:
            logger.error(
                f"[DbtMetrics] 🚨 Snapshot open/close mismatch: "
                f"opened={opened} closed={closed} "
                f"(pipeline={pipeline_id} snapshot={snapshot})"
            )

    @staticmethod
    def record_rows_affected(pipeline_id: str, model: str, rows: int):
        """Record rows written by a dbt model."""
        ude_dbt_model_rows_affected.labels(
            pipeline_id=pipeline_id,
            model=model,
        ).set(rows)

        if rows == 0:
            logger.warning(
                f"[DbtMetrics] ⚠️  Zero rows affected: "
                f"{model} (pipeline={pipeline_id}) — upstream issue?"
            )

    @staticmethod
    def record_contract_violation(pipeline_id: str, column: str):
        """Record a dbt source contract violation."""
        ude_dbt_contract_violations_total.labels(
            pipeline_id=pipeline_id,
            column=column,
        ).inc()
        logger.error(
            f"[DbtMetrics] 🚨 Contract violation: column={column} "
            f"(pipeline={pipeline_id}) — edge case gate has a gap"
        )