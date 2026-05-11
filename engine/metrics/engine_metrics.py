# engine/metrics/engine_metrics.py
# Prometheus metric emitters for UDE v2 engine
# Metrics are emitted at every layer — not just the API boundary
# Scraped by Prometheus at FastAPI /metrics endpoint

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Summary,
    REGISTRY,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
import logging

logger = logging.getLogger(__name__)

# ── Ingestion metrics ─────────────────────────────────────────────────────────

ude_batch_records_total = Counter(
    "ude_batch_records_total",
    "Total records pulled from Pub/Sub per batch",
    ["pipeline_id"],
)

ude_batch_duration_seconds = Histogram(
    "ude_batch_duration_seconds",
    "End-to-end batch processing duration in seconds",
    ["pipeline_id"],
    buckets=[1, 5, 10, 15, 20, 25, 30, 45, 60, 90, 120],
)

ude_pubsub_messages_pulled = Counter(
    "ude_pubsub_messages_pulled_total",
    "Total messages pulled from Pub/Sub",
    ["pipeline_id", "subscription"],
)

# ── Edge case metrics ─────────────────────────────────────────────────────────

ude_quarantine_total = Counter(
    "ude_quarantine_total",
    "Total records sent to quarantine",
    ["pipeline_id", "reason"],
)

ude_quarantine_rate = Gauge(
    "ude_quarantine_rate",
    "Quarantine rate for last batch (0.0 - 1.0)",
    ["pipeline_id"],
)

ude_duplicates_removed_total = Counter(
    "ude_duplicates_removed_total",
    "Total duplicate records removed",
    ["pipeline_id"],
)

ude_late_arrivals_total = Counter(
    "ude_late_arrivals_total",
    "Total late arrival records flagged",
    ["pipeline_id"],
)

ude_null_rate = Gauge(
    "ude_null_rate",
    "Null rate in last batch (0.0 - 1.0)",
    ["pipeline_id"],
)

# ── Schema metrics ────────────────────────────────────────────────────────────

ude_schema_version = Gauge(
    "ude_schema_version",
    "Current locked schema version per pipeline",
    ["pipeline_id"],
)

ude_schema_evolution_total = Counter(
    "ude_schema_evolution_total",
    "Total schema evolution events",
    ["pipeline_id", "deviation_type"],
)

ude_schema_deviation_total = Counter(
    "ude_schema_deviation_total",
    "Total schema deviation checks by outcome",
    ["pipeline_id", "status"],
)

# ── Staging metrics ───────────────────────────────────────────────────────────

ude_staging_rows_written = Counter(
    "ude_staging_rows_written_total",
    "Total rows written to BigQuery raw_staging",
    ["pipeline_id"],
)

ude_staging_write_duration = Histogram(
    "ude_staging_write_duration_seconds",
    "Time to write a batch to BigQuery staging",
    ["pipeline_id"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

# ── Checkpoint metrics ────────────────────────────────────────────────────────

ude_checkpoints_total = Counter(
    "ude_checkpoints_total",
    "Total batch checkpoints written",
    ["pipeline_id", "status"],
)

ude_active_pipelines = Gauge(
    "ude_active_pipelines",
    "Number of active pipelines being processed",
)


class EngineMetrics:
    """
    Helper class for emitting engine metrics.
    Called from each layer after key operations.
    """

    @staticmethod
    def record_batch_pulled(pipeline_id: str, record_count: int, subscription: str):
        ude_batch_records_total.labels(pipeline_id=pipeline_id).inc(record_count)
        ude_pubsub_messages_pulled.labels(
            pipeline_id=pipeline_id,
            subscription=subscription,
        ).inc(record_count)

    @staticmethod
    def record_edge_case_result(
        pipeline_id: str,
        quarantined: int,
        duplicates: int,
        late_arrivals: int,
        null_rate: float,
        quarantine_rate: float,
        failure_reason: str = "MIXED",
    ):
        if quarantined > 0:
            ude_quarantine_total.labels(
                pipeline_id=pipeline_id,
                reason=failure_reason,
            ).inc(quarantined)

        ude_quarantine_rate.labels(pipeline_id=pipeline_id).set(quarantine_rate)
        ude_duplicates_removed_total.labels(pipeline_id=pipeline_id).inc(duplicates)
        ude_late_arrivals_total.labels(pipeline_id=pipeline_id).inc(late_arrivals)
        ude_null_rate.labels(pipeline_id=pipeline_id).set(null_rate)

    @staticmethod
    def record_schema_deviation(pipeline_id: str, status: str):
        ude_schema_deviation_total.labels(
            pipeline_id=pipeline_id,
            status=status,
        ).inc()
        if status == "EVOLVED":
            ude_schema_evolution_total.labels(
                pipeline_id=pipeline_id,
                deviation_type="EVOLVED",
            ).inc()

    @staticmethod
    def record_schema_version(pipeline_id: str, version: int):
        ude_schema_version.labels(pipeline_id=pipeline_id).set(version)

    @staticmethod
    def record_staging_write(pipeline_id: str, rows: int, duration: float):
        ude_staging_rows_written.labels(pipeline_id=pipeline_id).inc(rows)
        ude_staging_write_duration.labels(pipeline_id=pipeline_id).observe(duration)

    @staticmethod
    def record_checkpoint(pipeline_id: str, status: str):
        ude_checkpoints_total.labels(
            pipeline_id=pipeline_id,
            status=status,
        ).inc()

    @staticmethod
    def record_batch_duration(pipeline_id: str, duration: float):
        ude_batch_duration_seconds.labels(pipeline_id=pipeline_id).observe(duration)

    @staticmethod
    def set_active_pipelines(count: int):
        ude_active_pipelines.set(count)