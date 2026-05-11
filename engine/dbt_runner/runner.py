# engine/dbt_runner/runner.py
# Orchestrates dbt from the engine
# The engine triggers dbt — it does NOT understand dbt internals
# Sequence: dbt run → dbt snapshot → dbt test
# Each step must pass before the next runs
# Failure at any step → nack messages, no checkpoint

import subprocess
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DBT_DIR = Path("dbt")
DBT_PROFILES_DIR = Path("dbt")


class DbtRunner:
    """
    Runs dbt commands as subprocesses.
    Passes batch_id as a dbt var for per-batch filtering and traceability.

    Sequence per micro-batch:
      1. dbt run --select staging.{pipeline}
      2. dbt snapshot --select {pipeline}_snapshot   (SCD Type 2 only)
      3. dbt run --select marts.{pipeline}            (SCD Type 1)
      4. dbt test --select {pipeline}
    """

    def __init__(self, target: str = "dev"):
        self.target = target
        self.dbt_dir = DBT_DIR.resolve()
        self.profiles_dir = DBT_PROFILES_DIR.resolve()
        logger.info(
            f"[DbtRunner] Initialized | target={target} | "
            f"dbt_dir={self.dbt_dir}"
        )

    def _run_command(self, args: list[str], batch_id: str) -> dict:
        """
        Run a dbt command and return result dict.
        Returns: {success: bool, command: str, returncode: int, output: str}
        """
        cmd = [
            "dbt", *args,
            "--project-dir", str(self.dbt_dir),
            "--profiles-dir", str(self.profiles_dir),
            "--target", self.target,
            "--vars", f"{{batch_id: '{batch_id}'}}",
            "--no-use-colors",
        ]

        cmd_str = " ".join(cmd)
        logger.info(f"[DbtRunner] Running: {cmd_str}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.dbt_dir),
            )

            output = result.stdout + result.stderr
            success = result.returncode == 0

            if success:
                logger.info(f"[DbtRunner] {args[0]} succeeded")
            else:
                logger.error(
                    f"[DbtRunner]  {args[0]} failed (rc={result.returncode})"
                )
                logger.error(f"[DbtRunner] Output:\n{output[-2000:]}")

            return {
                "success": success,
                "command": cmd_str,
                "returncode": result.returncode,
                "output": output,
            }

        except FileNotFoundError:
            logger.error("[DbtRunner] dbt not found — is it installed in venv?")
            return {
                "success": False,
                "command": cmd_str,
                "returncode": -1,
                "output": "dbt executable not found",
            }
        except Exception as e:
            logger.error(f"[DbtRunner] Unexpected error: {e}")
            return {
                "success": False,
                "command": cmd_str,
                "returncode": -1,
                "output": str(e),
            }

    def run_staging(self, pipeline_id: str, batch_id: str) -> dict:
        """Run staging model for a pipeline."""
        return self._run_command(
            ["run", "--select", f"staging.{pipeline_id}_staged"],
            batch_id,
        )

    def run_snapshot(self, pipeline_id: str, batch_id: str) -> dict:
        """Run dbt snapshot for SCD Type 2."""
        return self._run_command(
            ["snapshot", "--select", f"{pipeline_id}_snapshot"],
            batch_id,
        )

    def run_mart(self, pipeline_id: str, batch_id: str) -> dict:
        """Run mart incremental model for SCD Type 1."""
        return self._run_command(
            ["run", "--select", f"marts.dim_{pipeline_id}"],
            batch_id,
        )

    def run_tests(self, pipeline_id: str, batch_id: str) -> dict:
        """
        Run dbt tests after transformation.
        Test failure blocks checkpoint — batch is reprocessed next cycle.
        """
        return self._run_command(
            ["test", "--select", f"dim_{pipeline_id}"],
            batch_id,
        )

    def run_full_pipeline(
        self,
        pipeline_id: str,
        batch_id: str,
        scd_type: int = 2,
    ) -> dict:
        """
        Run the full dbt pipeline for a batch.
        Returns overall success + individual step results.

        SCD Type 2: staging → snapshot → tests
        SCD Type 1: staging → mart → tests
        """
        steps = {}

        # Step 1: Staging model
        steps["staging"] = self.run_staging(pipeline_id, batch_id)
        if not steps["staging"]["success"]:
            return {"success": False, "steps": steps, "failed_at": "staging"}

        # Step 2: SCD transformation
        if scd_type == 2:
            steps["snapshot"] = self.run_snapshot(pipeline_id, batch_id)
            if not steps["snapshot"]["success"]:
                return {"success": False, "steps": steps, "failed_at": "snapshot"}

        # Always run mart — needed for tests regardless of SCD type
        steps["mart"] = self.run_mart(pipeline_id, batch_id)
        if not steps["mart"]["success"]:
            return {"success": False, "steps": steps, "failed_at": "mart"}

        # Step 3: Tests — gate for checkpoint
        steps["tests"] = self.run_tests(pipeline_id, batch_id)
        if not steps["tests"]["success"]:
            return {"success": False, "steps": steps, "failed_at": "tests"}

        logger.info(
            f"[DbtRunner]  Full pipeline complete for "
            f"'{pipeline_id}' batch={batch_id}"
        )
        return {"success": True, "steps": steps, "failed_at": None}