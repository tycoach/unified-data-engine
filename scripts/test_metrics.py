# scripts/test_metrics.py
# End-to-end test of Phase 8 — observability
# Tests: metric emission, /metrics endpoint, alert rules exist
# Run: python scripts/test_metrics.py

import sys
import json
import time
import logging
import threading
import urllib.request

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"


def start_server():
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, log_level="warning")


def wait_for_api(retries=10):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(f"{API_BASE}/", timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


def test_emit_metrics():
    logger.info("\n=== TEST 1: Emit engine metrics ===")
    from engine.metrics.engine_metrics import EngineMetrics
    from engine.metrics.dbt_metrics import DbtMetrics

    EngineMetrics.record_batch_pulled("customers", 100, "raw.customers-sub")
    EngineMetrics.record_edge_case_result(
        pipeline_id="customers",
        quarantined=5,
        duplicates=2,
        late_arrivals=1,
        null_rate=0.02,
        quarantine_rate=0.05,
        failure_reason="NULL_VIOLATION",
    )
    EngineMetrics.record_schema_deviation("customers", "MATCH")
    EngineMetrics.record_schema_version("customers", 2)
    EngineMetrics.record_staging_write("customers", 95, 0.08)
    EngineMetrics.record_checkpoint("customers", "COMPLETE")
    EngineMetrics.record_batch_duration("customers", 1.2)
    EngineMetrics.set_active_pipelines(2)

    DbtMetrics.record_run_duration("customers", "snapshot", 0.49)
    DbtMetrics.record_run_result("customers", True)
    DbtMetrics.record_snapshot_changes("customers", "customers_snapshot", 795, 795)
    DbtMetrics.record_rows_affected("customers", "dim_customers", 95)

    logger.info(" All metrics emitted")


def test_metrics_endpoint():
    logger.info("\n=== TEST 2: /metrics endpoint ===")
    url = f"{API_BASE}/metrics"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()

    assert "ude_batch_records_total" in body
    assert "ude_quarantine_rate" in body
    assert "ude_dbt_run_duration_seconds" in body
    assert "ude_snapshot_records_opened_total" in body
    assert "ude_staging_rows_written_total" in body

    lines = [l for l in body.split("\n") if l and not l.startswith("#")]
    logger.info(f" /metrics returned {len(lines)} metric lines")
    logger.info(f"   Sample: {lines[:3]}")


def test_alert_rules_exist():
    logger.info("\n=== TEST 3: Alert rules file ===")
    from pathlib import Path
    alerts_path = Path("monitoring/prometheus/alerts.yml")
    assert alerts_path.exists(), "alerts.yml not found"

    content = alerts_path.read_text()
    assert "HighQuarantineRate" in content
    assert "DbtTestFailure" in content
    assert "SchemaDeviationDetected" in content
    assert "SnapshotMismatch" in content
    logger.info("All alert rules present")


def test_dashboard_files():
    logger.info("\n=== TEST 4: Grafana dashboard files ===")
    from pathlib import Path
    dashboards = list(Path("monitoring/grafana/dashboards").glob("*.json"))
    logger.info(f" Found {len(dashboards)} dashboards: {[d.name for d in dashboards]}")
    assert len(dashboards) >= 2


if __name__ == "__main__":
    # Emit metrics first (before server starts)
    test_emit_metrics()

    # Start API server
    logger.info("\nStarting API server...")
    thread = threading.Thread(target=start_server, daemon=True)
    thread.start()

    if not wait_for_api():
        logger.error(" API failed to start")
        sys.exit(1)

    test_metrics_endpoint()
    test_alert_rules_exist()
    test_dashboard_files()

    logger.info("\n Phase 8 observability — all tests passed.")
    logger.info(f"View metrics: {API_BASE}/metrics")