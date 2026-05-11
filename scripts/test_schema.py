# scripts/test_schema.py
# End-to-end test of Phase 3 — schema layer
# Tests: infer → lock → deviation check → contract write
# Run: python scripts/test_schema.py

import sys
import json
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from engine.schema.inferencer import infer_schema
from engine.schema.registry import SchemaRegistry
from engine.schema.deviation import check_deviation
from engine.schema.contract_writer import write_contract, read_contract


# ── Sample records simulating a real batch ────────────────────────────────────
SAMPLE_RECORDS = [
    {"customer_id": "C-0001", "email": "u1@test.com", "city": "Lagos",
     "country": "NG", "tier": "free", "updated_at": "2026-05-08T23:00:00"},
    {"customer_id": "C-0002", "email": "u2@test.com", "city": "London",
     "country": "UK", "tier": "pro", "updated_at": "2026-05-08T23:00:00"},
    {"customer_id": "C-0003", "email": None, "city": "Abuja",
     "country": "NG", "tier": "enterprise", "updated_at": "2026-05-08T23:00:00"},
]

# ── EVOLVED batch — adds a new column 'phone' ─────────────────────────────────
EVOLVED_RECORDS = [
    {"customer_id": "C-0001", "email": "u1@test.com", "city": "Lagos",
     "country": "NG", "tier": "free", "updated_at": "2026-05-08T23:00:00",
     "phone": "+234-800-0001"},
]

# ── BROKEN batch — removes 'country' column ───────────────────────────────────
BROKEN_RECORDS = [
    {"customer_id": "C-0001", "email": "u1@test.com", "city": "Lagos",
     "tier": "free", "updated_at": "2026-05-08T23:00:00"},
]


def test_infer_and_lock():
    logger.info("\n=== TEST 1: Infer + Lock ===")
    registry = SchemaRegistry()

    # Clean up any existing schema for clean test
    registry.delete("customers")

    schema = infer_schema(SAMPLE_RECORDS, pipeline_id="customers")
    logger.info(f"Inferred fields: {list(schema['fields'].keys())}")

    locked = registry.lock(schema)
    logger.info(f"Locked at version: {locked['version']}")
    assert locked["version"] == 1
    assert locked["status"] == "LOCKED"
    logger.info("Infer + Lock PASSED")
    return locked


def test_match_deviation(locked_schema):
    logger.info("\n=== TEST 2: MATCH deviation ===")
    incoming = infer_schema(SAMPLE_RECORDS, pipeline_id="customers")
    result = check_deviation("customers", locked_schema, incoming["fields"])
    assert result.status == "MATCH", f"Expected MATCH, got {result.status}"
    logger.info(" MATCH deviation PASSED")


def test_evolved_deviation(locked_schema):
    logger.info("\n=== TEST 3: EVOLVED deviation ===")
    registry = SchemaRegistry()
    incoming = infer_schema(EVOLVED_RECORDS, pipeline_id="customers")
    result = check_deviation("customers", locked_schema, incoming["fields"])
    assert result.status == "EVOLVED", f"Expected EVOLVED, got {result.status}"
    assert "phone" in result.updated_fields

    # Evolve the registry
    evolved = registry.evolve(
        "customers",
        result.updated_fields,
        reason="; ".join(result.details)
    )
    assert evolved["version"] == 2
    logger.info("EVOLVED deviation PASSED")
    return evolved


def test_broken_deviation(locked_schema):
    logger.info("\n=== TEST 4: BROKEN deviation ===")
    incoming = infer_schema(BROKEN_RECORDS, pipeline_id="customers")
    result = check_deviation("customers", locked_schema, incoming["fields"])
    assert result.status == "BROKEN", f"Expected BROKEN, got {result.status}"
    logger.info("BROKEN deviation PASSED")


def test_contract_writer(schema):
    logger.info("\n=== TEST 5: Contract writer ===")
    write_contract(schema)
    content = read_contract()
    assert content is not None
    assert "customers_staged" in content
    assert "contract" in content
    logger.info(f"Contract written:\n{content}")


if __name__ == "__main__":
    locked = test_infer_and_lock()
    test_match_deviation(locked)
    evolved = test_evolved_deviation(locked)
    test_broken_deviation(locked)
    test_contract_writer(evolved)

    logger.info("\n all tests passed.")