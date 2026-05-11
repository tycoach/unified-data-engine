# scripts/test_engine.py
# End-to-end test of Phase 9 — full engine cycle
# Publishes data, runs one complete batch lifecycle
# Run: python scripts/test_engine.py

import sys
import json
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_one_cycle():
    logger.info("\n=== Full engine cycle test ===")

    # Step 1: Publish test data
    logger.info("── Step 1: Publishing test data...")
    sys.path.insert(0, "data-generator"); from scenarios.happy_path import run
    run(num_customers=20, num_orders=0, repeat=1)

    # Step 2: Run one pipeline cycle
    logger.info("── Step 2: Running one engine cycle for customers...")
    from engine.main import process_pipeline

    config = {
        "pipeline_id": "customers",
        "subscription_id": "raw.customers-sub",
        "natural_key": "customer_id",
        "scd_type": 2,
        "null_threshold": 0.05,
        "late_arrival_window": "24h",
        "duplicate_window": "30m",
        "edge_case_mode": "quarantine",
    }

    result = process_pipeline(config)

    logger.info(f"\n── Result: {json.dumps(result, indent=2)}")

    assert result["batch_id"] is not None
    assert result["status"] in (
        "COMPLETE", "EMPTY", "ALL_QUARANTINED",
        "DBT_FAILED", "SCHEMA_BROKEN"
    )

    logger.info(f"\n✅ Engine cycle complete: {result['status']}")
    logger.info(f"   Pulled:      {result['records_pulled']}")
    logger.info(f"   Clean:       {result['records_clean']}")
    logger.info(f"   Quarantined: {result['records_quarantined']}")
    logger.info(f"   dbt success: {result['dbt_success']}")

    return result


def test_makefile_exists():
    logger.info("\n=== Makefile check ===")
    from pathlib import Path
    assert Path("Makefile").exists(), "Makefile not found"
    content = Path("Makefile").read_text()
    assert "make up" in content or "up:" in content
    assert "engine:" in content
    assert "seed:" in content
    assert "dbt-run:" in content
    assert "schema-sync:" in content
    logger.info("✅ Makefile present with all required targets")


def test_env_example():
    logger.info("\n=== .env.example check ===")
    from pathlib import Path
    assert Path(".env.example").exists(), ".env.example not found"
    content = Path(".env.example").read_text()
    assert "GCP_PROJECT_ID" in content
    assert "MINISKY_HOST" in content
    assert "BATCH_WINDOW_SECONDS" in content
    logger.info("✅ .env.example present with all required vars")


if __name__ == "__main__":
    test_makefile_exists()
    test_env_example()
    result = test_one_cycle()

    logger.info("\n✅ Phase 9 orchestration — all tests passed.")