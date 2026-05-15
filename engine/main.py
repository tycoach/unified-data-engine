# engine/main.py
# The micro-batch loop — heart of the UDE v2 engine
# Wires together all layers: ingestion → schema → edge case → staging → dbt → checkpoint
#
# Loop rhythm: 30-second windows
# One iteration = one complete batch lifecycle
#
# Happy path:
#   1. Pull messages from Pub/Sub (30s window)
#   2. Infer or check schema deviation
#   3. Run edge case gate
#   4. Write clean records to BigQuery staging
#   5. Trigger dbt (staging → snapshot/mart → tests)
#   6. Checkpoint + ack messages
#
# Failure paths:
#   BROKEN schema    → quarantine batch, nack, alert
#   Edge case > 10%  → quarantine dirty, continue with clean
#   dbt test fail    → nack, no checkpoint, reprocess next cycle
#
# Hot-reload: PIPELINES is reloaded at the top of every cycle.
# API-registered pipelines (via POST /pipeline/) are picked up
# without an engine restart.

import time
import logging
import signal
import sys
from datetime import datetime, timezone

# Engine layers
from engine.ingestion.consumer import MicroBatchConsumer
from engine.ingestion.offset_manager import OffsetManager
from engine.schema.inferencer import infer_schema
from engine.schema.registry import SchemaRegistry
from engine.schema.deviation import check_deviation
from engine.schema.contract_writer import write_contract
from engine.staging.edge_case_handler import EdgeCaseHandler
from engine.staging.staging_writer import StagingWriter
from engine.dbt_runner.runner import DbtRunner
from engine.dbt_runner.results import DbtResults
from engine.state.checkpoint_manager import CheckpointManager
from engine.metrics.engine_metrics import EngineMetrics
from engine.metrics.dbt_metrics import DbtMetrics

# Pushgateway auto-push
try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, push_to_gateway
    _PUSH_ENABLED = True
    _PUSHGATEWAY_URL = "localhost:9091"
except ImportError:
    _PUSH_ENABLED = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Engine config (loaded once at startup) ────────────────────────────────────
from config.loader import load_pipelines, load_engine_config

_engine_config   = load_engine_config()
_engine_settings = _engine_config.get("engine", {})

PROJECT_ID           = _engine_settings.get("project_id", "local-dev-project")
BATCH_WINDOW_SECONDS = _engine_settings.get("batch_window_seconds", 30)
LOOP_SLEEP_SECONDS   = _engine_settings.get("loop_sleep_seconds", 1)

# NOTE: PIPELINES is NOT loaded here at module level.
# It is reloaded at the top of every cycle in run() so that
# pipelines registered via POST /pipeline/ are picked up
# without an engine restart. See run() below.

# Graceful shutdown flag
_running = True


def handle_shutdown(signum, frame):
    global _running
    logger.info("[Main] Shutdown signal received — finishing current batch...")
    _running = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def process_pipeline(config: dict) -> dict:
    """
    Run one complete micro-batch lifecycle for a single pipeline.
    Returns result dict with status and metrics.
    """
    pipeline_id     = config["pipeline_id"]
    subscription_id = config["subscription_id"]
    scd_type        = config["scd_type"]

    batch_start = time.time()
    result = {
        "pipeline_id":        pipeline_id,
        "batch_id":           None,
        "status":             "UNKNOWN",
        "records_pulled":     0,
        "records_clean":      0,
        "records_quarantined": 0,
        "dbt_success":        False,
    }

    # ── Initialize components ─────────────────────────────────────────────────
    consumer = MicroBatchConsumer(
        project_id=PROJECT_ID,
        subscription_id=subscription_id,
        batch_window_seconds=BATCH_WINDOW_SECONDS,
    )
    offset_mgr     = OffsetManager(pipeline_id)
    registry       = SchemaRegistry()
    checkpoint_mgr = CheckpointManager(pipeline_id)
    dbt_runner     = DbtRunner(target="dev")

    # Open batch
    batch_id           = offset_mgr.open_batch()
    result["batch_id"] = batch_id
    logger.info(f"[Main] ═══ Pipeline: {pipeline_id} | Batch: {batch_id} ═══")

    # ── Pull messages ─────────────────────────────────────────────────────────
    messages, ack_ids         = consumer.pull_batch()
    result["records_pulled"]  = len(messages)

    if not messages:
        logger.info(f"[Main] No messages for {pipeline_id} — skipping batch")
        result["status"] = "EMPTY"
        return result

    EngineMetrics.record_batch_pulled(pipeline_id, len(messages), subscription_id)

    # ── Schema check ──────────────────────────────────────────────────────────
    incoming_schema = infer_schema(messages, pipeline_id)
    locked_schema   = registry.get_locked(pipeline_id)

    if not locked_schema:
        # First batch — lock schema and generate dbt contract
        logger.info(f"[Main] First batch for '{pipeline_id}' — locking schema")
        locked_schema = registry.lock(incoming_schema)
        write_contract(locked_schema)
        EngineMetrics.record_schema_version(pipeline_id, locked_schema["version"])
    else:
        # Check for deviation
        deviation = check_deviation(
            pipeline_id,
            locked_schema,
            incoming_schema["fields"],
        )
        EngineMetrics.record_schema_deviation(pipeline_id, deviation.status)

        if deviation.status == "BROKEN":
            logger.error(
                f"[Main] 🚨 BROKEN schema deviation — quarantining batch {batch_id}"
            )
            writer = StagingWriter(pipeline_id)
            writer.write_quarantine(messages, batch_id)
            consumer.nack(ack_ids)
            offset_mgr.fail_batch(len(messages))
            checkpoint_mgr.write_failure(
                batch_id,
                failed_at="schema",
                reason="; ".join(deviation.details),
            )
            result["status"] = "SCHEMA_BROKEN"
            return result

        elif deviation.status == "EVOLVED":
            logger.info(f"[Main] ⚠️  EVOLVED schema — updating registry + contract")
            locked_schema = registry.evolve(
                pipeline_id,
                deviation.updated_fields,
                reason="; ".join(deviation.details),
            )
            write_contract(locked_schema)
            EngineMetrics.record_schema_version(pipeline_id, locked_schema["version"])

    # ── Edge case gate ────────────────────────────────────────────────────────
    handler     = EdgeCaseHandler(config)
    gate_result = handler.run(messages, batch_id, locked_schema)

    EngineMetrics.record_edge_case_result(
        pipeline_id=pipeline_id,
        quarantined=gate_result.quarantine_count,
        duplicates=len(gate_result.discarded_duplicates),
        late_arrivals=gate_result.late_arrival_count,
        null_rate=gate_result.null_rate,
        quarantine_rate=gate_result.quarantine_count / max(len(messages), 1),
    )

    result["records_clean"]      = gate_result.clean_count
    result["records_quarantined"] = gate_result.quarantine_count

    # Write dirty records to quarantine
    if gate_result.dirty_records:
        writer = StagingWriter(pipeline_id)
        writer.write_quarantine(gate_result.dirty_records, batch_id)

    if not gate_result.clean_records:
        logger.warning(f"[Main] No clean records after gate — nacking batch")
        consumer.nack(ack_ids)
        offset_mgr.fail_batch(0)
        result["status"] = "ALL_QUARANTINED"
        return result

    # ── Write to BigQuery staging ─────────────────────────────────────────────
    staging_start    = time.time()
    writer           = StagingWriter(pipeline_id)
    rows_written     = writer.write(gate_result.clean_records, batch_id, locked_schema)
    staging_duration = time.time() - staging_start

    EngineMetrics.record_staging_write(pipeline_id, rows_written, staging_duration)
    logger.info(f"[Main] Staged {rows_written} rows in {staging_duration:.2f}s")

    # ── Trigger dbt ───────────────────────────────────────────────────────────
    dbt_start  = time.time()
    dbt_result = dbt_runner.run_full_pipeline(
        pipeline_id=pipeline_id,
        batch_id=batch_id,
        scd_type=scd_type,
    )
    dbt_duration = time.time() - dbt_start

    DbtMetrics.record_run_duration(pipeline_id, "full", dbt_duration)
    DbtMetrics.record_run_result(pipeline_id, dbt_result["success"])
    result["dbt_success"] = dbt_result["success"]

    if not dbt_result["success"]:
        failed_at = dbt_result.get("failed_at", "unknown")
        logger.error(
            f"[Main] ------ dbt failed at '{failed_at}' — nacking batch {batch_id}"
        )
        consumer.nack(ack_ids)
        offset_mgr.fail_batch(rows_written)
        checkpoint_mgr.write_failure(batch_id, failed_at, "dbt failure")
        EngineMetrics.record_checkpoint(pipeline_id, "FAILED")
        result["status"] = "DBT_FAILED"
        return result

    # ── Checkpoint + ack ──────────────────────────────────────────────────────
    checkpoint_ok = checkpoint_mgr.write(
        batch_id=batch_id,
        records_processed=rows_written,
        records_quarantined=gate_result.quarantine_count,
        schema_version=locked_schema["version"],
        dbt_result=dbt_result,
    )

    if checkpoint_ok:
        consumer.ack(ack_ids)
        offset_mgr.complete_batch(rows_written)
        EngineMetrics.record_checkpoint(pipeline_id, "COMPLETE")
        result["status"] = "COMPLETE"
    else:
        consumer.nack(ack_ids)
        result["status"] = "CHECKPOINT_FAILED"

    # Record total batch duration
    batch_duration = time.time() - batch_start
    EngineMetrics.record_batch_duration(pipeline_id, batch_duration)

    logger.info(
        f"[Main] ---- Batch {batch_id} {result['status']} | "
        f"clean={rows_written} quarantined={gate_result.quarantine_count} "
        f"duration={batch_duration:.2f}s"
    )

    return result


def _push_metrics(cycle_results: list[dict], active_pipeline_count: int):
    """Auto-push batch metrics to Pushgateway after every cycle."""
    if not _PUSH_ENABLED:
        return
    try:
        registry = CollectorRegistry()

        g_active   = Gauge('ude_active_pipelines', 'Active pipelines', registry=registry)
        c_records  = Counter('ude_batch_records_total', 'Records pulled', ['pipeline_id'], registry=registry)
        c_staging  = Counter('ude_staging_rows_written_total', 'Rows staged', ['pipeline_id'], registry=registry)
        g_schema   = Gauge('ude_schema_version', 'Schema version', ['pipeline_id'], registry=registry)
        g_qrate    = Gauge('ude_quarantine_rate', 'Quarantine rate', ['pipeline_id'], registry=registry)
        g_dbt      = Gauge('ude_dbt_run_status', 'dbt status', ['pipeline_id'], registry=registry)
        h_duration = Histogram(
            'ude_batch_duration_seconds', 'Batch duration',
            ['pipeline_id'],
            buckets=[1, 5, 10, 15, 20, 25, 30, 45, 60, 90, 120],
            registry=registry,
        )

        # Use live pipeline count passed from the cycle
        g_active.set(active_pipeline_count)

        schema_reg = SchemaRegistry()

        for result in cycle_results:
            pid     = result.get('pipeline_id', 'unknown')
            records = result.get('records_pulled', 0)
            clean   = result.get('records_clean', 0)
            qcount  = result.get('records_quarantined', 0)
            dbt_ok  = 1 if result.get('dbt_success') else 0

            if result.get('status') == 'EMPTY':
                continue

            if records > 0:
                c_records.labels(pipeline_id=pid).inc(records)
            if clean > 0:
                c_staging.labels(pipeline_id=pid).inc(clean)
                h_duration.labels(pipeline_id=pid).observe(BATCH_WINDOW_SECONDS + 1)

            g_qrate.labels(pipeline_id=pid).set(qcount / max(records, 1))
            g_dbt.labels(pipeline_id=pid).set(dbt_ok)

            schema = schema_reg.get_locked(pid)
            if schema:
                g_schema.labels(pipeline_id=pid).set(schema.get('version', 1))

        push_to_gateway(_PUSHGATEWAY_URL, job='ude_engine', registry=registry)
        logger.debug("[Main] ✅ Metrics pushed to Pushgateway")

    except Exception as e:
        logger.warning(f"[Main] Metrics push skipped: {e}")


def run():
    """
    Main engine loop — runs until shutdown signal.

    PIPELINES is reloaded at the top of every cycle so that pipelines
    registered via POST /pipeline/ are picked up without a restart.
    """
    logger.info("═" * 60)
    logger.info("  Unified Data Engine v2 — starting")
    logger.info("  Pipelines: loaded dynamically per cycle (hot-reload enabled)")
    logger.info(f"  Batch window: {BATCH_WINDOW_SECONDS}s")
    logger.info("═" * 60)

    cycle = 0

    while _running:
        cycle += 1
        logger.info(
            f"\n[Main] ── Cycle {cycle} ── {datetime.now(timezone.utc).isoformat()}"
        )

        # ── Hot-reload pipelines every cycle ─────────────────────────────────
        # Picks up pipelines registered via POST /pipeline/ without restart.
        # Also picks up new filesystem YAML files dropped into config/pipelines/.
        pipelines = load_pipelines()

        if cycle == 1 or cycle % 10 == 0:
            # Log pipeline list on first cycle and every 10 cycles
            logger.info(
                f"[Main] Active pipelines ({len(pipelines)}): "
                f"{[p['pipeline_id'] for p in pipelines]}"
            )

        EngineMetrics.set_active_pipelines(len(pipelines))

        cycle_results = []
        for config in pipelines:
            if not _running:
                break
            try:
                result = process_pipeline(config)
                cycle_results.append(result)
                logger.info(
                    f"[Main] Pipeline {result['pipeline_id']}: "
                    f"{result['status']} | "
                    f"pulled={result['records_pulled']} "
                    f"clean={result['records_clean']}"
                )
            except Exception as e:
                logger.error(
                    f"[Main] ---- Unhandled error in pipeline "
                    f"'{config['pipeline_id']}': {e}",
                    exc_info=True,
                )

        # Auto-push metrics to Pushgateway after every cycle
        if cycle_results:
            _push_metrics(cycle_results, active_pipeline_count=len(pipelines))

        if _running:
            logger.info(
                f"[Main] Cycle {cycle} complete — next cycle in {LOOP_SLEEP_SECONDS}s"
            )
            time.sleep(LOOP_SLEEP_SECONDS)

    logger.info("[Main] Engine stopped cleanly.")


if __name__ == "__main__":
    run()