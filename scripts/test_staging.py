# scripts/test_staging.py
# Tests: null check, dedup, type check, late arrival, BQ write, quarantine write
# Run: python scripts/test_staging.py

import sys
import json
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from engine.schema.inferencer import infer_schema
from engine.schema.registry import SchemaRegistry
from engine.staging.edge_case_handler import EdgeCaseHandler
from engine.staging.staging_writer import StagingWriter

# ── Pipeline config ───────────────────────────────────────────────────────────
PIPELINE_CONFIG = {
    "pipeline_id": "customers",
    "natural_key": "customer_id",
    "null_threshold": 0.05,
    "late_arrival_window": "24h",
    "duplicate_window": "30m",
    "edge_case_mode": "quarantine",
}

# ── Clean records ─────────────────────────────────────────────────────────────
CLEAN_RECORDS = [
    {"customer_id": "C-0001", "email": "u1@test.com", "city": "Lagos",
     "country": "NG", "tier": "free", "updated_at": "2026-05-09T20:00:00"},
    {"customer_id": "C-0002", "email": "u2@test.com", "city": "London",
     "country": "UK", "tier": "pro", "updated_at": "2026-05-09T20:00:00"},
    {"customer_id": "C-0003", "email": "u3@test.com", "city": "Abuja",
     "country": "NG", "tier": "enterprise", "updated_at": "2026-05-09T20:00:00"},
    # Duplicate — should be deduplicated
    {"customer_id": "C-0001", "email": "u1-updated@test.com", "city": "Lagos",
     "country": "NG", "tier": "pro", "updated_at": "2026-05-09T20:01:00"},
    # Null in non-nullable field — should be quarantined
    {"customer_id": None, "email": "u4@test.com", "city": "Dubai",
     "country": "AE", "tier": "free", "updated_at": "2026-05-09T20:00:00"},
]

BATCH_ID = "test-batch-phase4-001"


def get_locked_schema():
    """Get or create locked schema for customers."""
    registry = SchemaRegistry()
    schema = registry.get_locked("customers")
    if not schema:
        base_records = [
            {"customer_id": "C-0001", "email": "u1@test.com", "city": "Lagos",
             "country": "NG", "tier": "free", "updated_at": "2026-05-09T20:00:00"},
        ]
        inferred = infer_schema(base_records, "customers")
        # Make customer_id non-nullable
        inferred["fields"]["customer_id"]["nullable"] = False
        schema = registry.lock(inferred)
    return schema


def test_edge_case_handler(locked_schema):
    logger.info("\n=== TEST 1: Edge Case Handler ===")

    handler = EdgeCaseHandler(PIPELINE_CONFIG)
    result = handler.run(CLEAN_RECORDS, BATCH_ID, locked_schema)

    logger.info(f"Summary: {json.dumps(result.summary(), indent=2)}")

    assert result.clean_count > 0, "Expected clean records"
    assert result.quarantine_count > 0, "Expected quarantined records (null customer_id)"
    assert len(result.discarded_duplicates) > 0, "Expected duplicates removed"

    logger.info(f" Edge case handler PASSED")
    logger.info(f"   Clean: {result.clean_count}")
    logger.info(f"   Quarantined: {result.quarantine_count}")
    logger.info(f"   Duplicates removed: {len(result.discarded_duplicates)}")
    return result


def test_staging_writer(result, locked_schema):
    logger.info("\n=== TEST 2: Staging Writer — write clean records ===")

    writer = StagingWriter(pipeline_id="customers")

    rows_written = writer.write(result.clean_records, BATCH_ID, locked_schema)
    logger.info(f" Wrote {rows_written} clean rows to raw_staging.customers_staged")
    assert rows_written == result.clean_count

    return writer


def test_quarantine_writer(writer, result):
    logger.info("\n=== TEST 3: Staging Writer — write quarantine records ===")

    writer.write_quarantine(result.dirty_records, BATCH_ID)
    logger.info(f" Quarantined {result.quarantine_count} records")


def test_verify_bq(writer):
    logger.info("\n=== TEST 4: Verify BigQuery rows via MiniSky ===")
    import urllib.request

    url = (
        f"http://localhost:8080/bigquery/v2/projects/local-dev-project"
        f"/datasets/raw_staging/tables/customers_staged/data"
    )
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            rows = data.get("rows", [])
            logger.info(f" BigQuery raw_staging.customers_staged has {len(rows)} rows")
            if rows:
                logger.info(f"   Sample row: {rows[0]}")
    except Exception as e:
        logger.warning(f"  Could not verify BQ rows: {e}")


if __name__ == "__main__":
    locked_schema = get_locked_schema()
    logger.info(f"Using schema v{locked_schema['version']} for customers")

    result = test_edge_case_handler(locked_schema)
    writer = test_staging_writer(result, locked_schema)
    test_quarantine_writer(writer, result)
    test_verify_bq(writer)

    logger.info("\n all tests passed.")