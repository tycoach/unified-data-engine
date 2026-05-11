# scripts/test_state.py
# End-to-end test of Phase 6 — state & checkpointing
# Tests: bigtable set/get, schema version cache,
#        checkpoint write, failure checkpoint, history
# Run: python scripts/test_state.py

import sys
import json
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from engine.state.bigtable_client import BigtableClient
from engine.state.checkpoint_manager import CheckpointManager

BATCH_ID = "test-batch-phase6-001"
PIPELINE_ID = "customers"


def test_bigtable_client():
    logger.info("\n===  BigtableClient set/get/delete ===")
    client = BigtableClient()

    # Set
    ok = client.set("test#key1", {"foo": "bar", "count": 42})
    assert ok, "SET failed"

    # Get
    val = client.get("test#key1")
    assert val == {"foo": "bar", "count": 42}, f"GET mismatch: {val}"
    logger.info(f" GET returned: {val}")

    # Exists
    assert client.exists("test#key1")
    assert not client.exists("test#nonexistent")

    # Delete
    client.delete("test#key1")
    assert not client.exists("test#key1")

    logger.info("BigtableClient PASSED")


def test_schema_version_cache():
    logger.info("\n=== TEST 2: Schema version cache ===")
    client = BigtableClient()

    client.set_schema_version(PIPELINE_ID, 3)
    version = client.get_schema_version(PIPELINE_ID)
    assert version == 3, f"Expected 3, got {version}"
    logger.info(f" Schema version cached: v{version}")

    # None for unknown pipeline
    version = client.get_schema_version("nonexistent")
    assert version is None
    logger.info("Schema version cache PASSED")


def test_checkpoint_write():
    logger.info("\n=== TEST 3: Checkpoint write ===")
    manager = CheckpointManager(PIPELINE_ID)

    # Simulate successful dbt result
    dbt_result = {
        "success": True,
        "failed_at": None,
        "steps": {
            "staging": {"success": True},
            "snapshot": {"success": True},
            "tests": {"success": True},
        },
    }

    ok = manager.write(
        batch_id=BATCH_ID,
        records_processed=95,
        records_quarantined=5,
        schema_version=3,
        dbt_result=dbt_result,
    )
    assert ok, "Checkpoint write failed"

    # Verify checkpoint was written
    client = BigtableClient()
    checkpoint = client.get_checkpoint(BATCH_ID)
    assert checkpoint is not None
    assert checkpoint["status"] == "COMPLETE"
    assert checkpoint["records_processed"] == 95
    assert checkpoint["records_quarantined"] == 5
    assert checkpoint["schema_version"] == 3

    logger.info(f"Checkpoint written: {json.dumps(checkpoint, indent=2)}")
    logger.info("Checkpoint write PASSED")


def test_failure_checkpoint():
    logger.info("\n=== TEST 4: Failure checkpoint ===")
    manager = CheckpointManager(PIPELINE_ID)

    failed_batch_id = "test-batch-phase6-FAILED"
    ok = manager.write_failure(
        batch_id=failed_batch_id,
        failed_at="tests",
        reason="unique(customer_id) test failed — duplicate found",
    )
    assert ok

    client = BigtableClient()
    checkpoint = client.get_checkpoint(failed_batch_id)
    assert checkpoint["status"] == "FAILED"
    assert checkpoint["failed_at"] == "tests"
    logger.info(f" Failure checkpoint: {checkpoint}")
    logger.info(" Failure checkpoint PASSED")


def test_last_checkpoint():
    logger.info("\n=== TEST 5: Get last checkpoint ===")
    manager = CheckpointManager(PIPELINE_ID)

    last = manager.get_last_checkpoint()
    assert last is not None
    assert last["batch_id"] == BATCH_ID
    logger.info(f" Last checkpoint: batch_id={last['batch_id']}")
    logger.info(" Last checkpoint PASSED")


def test_is_first_batch():
    logger.info("\n=== TEST 6: is_first_batch ===")
    manager_new = CheckpointManager("brand_new_pipeline")
    assert manager_new.is_first_batch() is True

    manager_existing = CheckpointManager(PIPELINE_ID)
    assert manager_existing.is_first_batch() is False

    logger.info(" is_first_batch PASSED")


def test_all_keys():
    logger.info("\n=== TEST 7: all_keys ===")
    client = BigtableClient()
    keys = client.all_keys()
    logger.info(f" State keys: {keys}")
    assert len(keys) > 0
    logger.info(" all_keys PASSED")


if __name__ == "__main__":
    test_bigtable_client()
    test_schema_version_cache()
    test_checkpoint_write()
    test_failure_checkpoint()
    test_last_checkpoint()
    test_is_first_batch()
    test_all_keys()

    logger.info("\n  state & checkpointing — all tests passed.")