# engine/dbt_runner/results.py
# Parses dbt run_results.json after each dbt run
# The engine reads pass/fail — it does NOT write test logic
# A test failure means the transformation produced unexpected output
# Engine does NOT checkpoint a batch whose tests fail

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RUN_RESULTS_PATH = Path("dbt/target/run_results.json")
MANIFEST_PATH = Path("dbt/target/manifest.json")


class DbtResults:
    """
    Parses dbt artifacts after a run.
    run_results.json → pass/fail per test
    manifest.json    → lineage graph for operator UI
    """

    @staticmethod
    def parse_run_results() -> dict:
        """
        Parse dbt/target/run_results.json.
        Returns summary of pass/fail per node.
        """
        if not RUN_RESULTS_PATH.exists():
            logger.warning("[DbtResults] run_results.json not found")
            return {"success": False, "results": [], "summary": {}}

        with open(RUN_RESULTS_PATH) as f:
            data = json.load(f)

        results = data.get("results", [])
        summary = {
            "pass": 0,
            "fail": 0,
            "warn": 0,
            "skip": 0,
            "error": 0,
        }
        failures = []

        for result in results:
            status = result.get("status", "unknown").lower()
            node_id = result.get("unique_id", "unknown")

            if status in ("pass", "success"):
                summary["pass"] += 1
            elif status == "fail":
                summary["fail"] += 1
                failures.append({
                    "node": node_id,
                    "status": status,
                    "message": result.get("message", ""),
                    "failures": result.get("failures", 0),
                })
            elif status == "warn":
                summary["warn"] += 1
            elif status == "skip":
                summary["skip"] += 1
            elif status == "error":
                summary["error"] += 1
                failures.append({
                    "node": node_id,
                    "status": status,
                    "message": result.get("message", ""),
                })

        overall_success = summary["fail"] == 0 and summary["error"] == 0

        if overall_success:
            logger.info(
                f"[DbtResults] All tests passed — "
                f"pass={summary['pass']} warn={summary['warn']}"
            )
        else:
            logger.error(
                f"[DbtResults]  Tests failed — "
                f"fail={summary['fail']} error={summary['error']}"
            )
            for f in failures:
                logger.error(f"  FAILED: {f['node']} — {f['message']}")

        return {
            "success": overall_success,
            "summary": summary,
            "failures": failures,
            "results": results,
        }

    @staticmethod
    def parse_manifest() -> dict:
        """
        Parse dbt/target/manifest.json for lineage.
        Returns node dependency graph for operator UI.
        """
        if not MANIFEST_PATH.exists():
            logger.warning("[DbtResults] manifest.json not found")
            return {}

        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)

        nodes = manifest.get("nodes", {})
        sources = manifest.get("sources", {})

        lineage = {}
        for node_id, node in nodes.items():
            lineage[node_id] = {
                "name": node.get("name"),
                "resource_type": node.get("resource_type"),
                "depends_on": node.get("depends_on", {}).get("nodes", []),
                "schema": node.get("schema"),
            }

        logger.info(
            f"[DbtResults] Parsed manifest: "
            f"{len(nodes)} nodes, {len(sources)} sources"
        )
        return lineage