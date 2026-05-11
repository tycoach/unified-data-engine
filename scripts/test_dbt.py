# scripts/test_dbt.py
# End-to-end test of Phase 5 — dbt layer
# Tests: dbt deps, dbt compile, dbt run, dbt snapshot, dbt test
# Run: python scripts/test_dbt.py

import sys
import subprocess
import logging
from pathlib import Path

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DBT_DIR = Path("dbt").resolve()
PROFILES_DIR = Path("dbt").resolve()
BATCH_ID = "test-batch-phase5-001"


def run_dbt(args: list[str], label: str) -> bool:
    cmd = [
        "dbt", *args,
        "--project-dir", str(DBT_DIR),
        "--profiles-dir", str(PROFILES_DIR),
        "--target", "dev",
        "--no-use-colors",
    ]
    logger.info(f"\n=== {label} ===")
    logger.info(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr

    if result.returncode == 0:
        logger.info(f" {label} PASSED")
        # Show last few lines
        lines = [l for l in output.split('\n') if l.strip()]
        for line in lines[-5:]:
            logger.info(f"  {line}")
    else:
        logger.error(f" {label} FAILED")
        logger.error(output[-3000:])

    return result.returncode == 0


if __name__ == "__main__":
    # Install dbt packages
    ok = run_dbt(["deps"], "dbt deps")
    if not ok:
        logger.error("dbt deps failed — check packages.yml")
        sys.exit(1)

    #  Compile to validate SQL
    ok = run_dbt(
        ["compile", "--vars", f"{{batch_id: '{BATCH_ID}'}}"],
        "dbt compile"
    )
    if not ok:
        logger.error("dbt compile failed — check SQL syntax")
        sys.exit(1)

    #  Run staging model
    ok = run_dbt(
        ["run", "--select", "staging.customers_staged",
         "--vars", f"{{batch_id: '{BATCH_ID}'}}"],
        "dbt run staging"
    )

    #  Run snapshot (SCD Type 2)
    ok = run_dbt(
        ["snapshot", "--select", "customers_snapshot",
         "--vars", f"{{batch_id: '{BATCH_ID}'}}"],
        "dbt snapshot"
    )

    # Run mart (SCD Type 1)
    ok = run_dbt(
        ["run", "--select", "marts.dim_customers",
         "--vars", f"{{batch_id: '{BATCH_ID}'}}"],
        "dbt run marts"
    )

    #  Run tests
    ok = run_dbt(
        ["test", "--select", "dim_customers",
         "--vars", f"{{batch_id: '{BATCH_ID}'}}"],
        "dbt test"
    )

    logger.info("\ndbt layer test complete.")