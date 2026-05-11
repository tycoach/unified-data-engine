# engine/state/checkpoint_manager.py
# Writes batch checkpoint ONLY after dbt run + tests pass
# This is the final gate before Pub/Sub ack
# A half-committed batch is the worst possible state — this prevents it
#
# Checkpoint sequence (all-or-nothing):
#   1. Write batch state to Bigtable
#   2. Update schema version in Bigtable
#   3. Update last committed offset in Bigtable
#   4. Ack Pub/Sub messages
#   5. Emit Prometheus metrics
#
# If anything fails before step 4, messages are nacked and reprocessed

import logging
from datetime import datetime, timezone
from engine.state.bigtable_client import BigtableClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Manages the checkpoint lifecycle for each micro-batch.
    """

    def __init__(self, pipeline_id: str):
        self.pipeline_id = pipeline_id
        self.state = BigtableClient()
        logger.info(
            f"[Checkpoint] Initialized for pipeline: {pipeline_id}"
        )

    def write(
        self,
        batch_id: str,
        records_processed: int,
        records_quarantined: int,
        schema_version: int,
        dbt_result: dict,
    ) -> bool:
        """
        Write a complete batch checkpoint.
        """
        checkpoint = {
            "batch_id": batch_id,
            "pipeline_id": self.pipeline_id,
            "checkpointed_at": datetime.now(timezone.utc).isoformat(),
            "records_processed": records_processed,
            "records_quarantined": records_quarantined,
            "schema_version": schema_version,
            "dbt_success": dbt_result.get("success", False),
            "dbt_failed_at": dbt_result.get("failed_at"),
            "status": "COMPLETE",
        }

        try:
            #  Write batch checkpoint
            ok = self.state.write_checkpoint(batch_id, checkpoint)
            if not ok:
                logger.error(
                    f"[Checkpoint] Failed to write checkpoint for {batch_id}"
                )
                return False

            #  Update schema version cache
            self.state.set_schema_version(self.pipeline_id, schema_version)

            #  Update last committed offset
            self.state.set_last_committed_batch(self.pipeline_id, batch_id)

            logger.info(
                f"[Checkpoint]  Batch {batch_id} checkpointed | "
                f"processed={records_processed} | "
                f"quarantined={records_quarantined} | "
                f"schema=v{schema_version}"
            )
            return True

        except Exception as e:
            logger.error(
                f"[Checkpoint]  Checkpoint failed for {batch_id}: {e}"
            )
            return False

    def write_failure(
        self,
        batch_id: str,
        failed_at: str,
        reason: str,
    ) -> bool:
        """
        Write a failure checkpoint — batch will be reprocessed.
        Called when dbt tests fail or processing errors occur.
        Messages are nacked — NOT acked.
        """
        checkpoint = {
            "batch_id": batch_id,
            "pipeline_id": self.pipeline_id,
            "checkpointed_at": datetime.now(timezone.utc).isoformat(),
            "failed_at": failed_at,
            "reason": reason,
            "status": "FAILED",
        }

        ok = self.state.write_checkpoint(batch_id, checkpoint)
        logger.warning(
            f"[Checkpoint]   Failure checkpoint written: "
            f"batch={batch_id} failed_at={failed_at}"
        )
        return ok

    def get_last_checkpoint(self) -> dict | None:
        """Get the last committed batch for this pipeline."""
        last = self.state.get_last_committed_batch(self.pipeline_id)
        if last:
            batch_id = last.get("batch_id")
            return self.state.get_checkpoint(batch_id)
        return None

    def get_schema_version(self) -> int | None:
        """Get cached schema version for this pipeline."""
        return self.state.get_schema_version(self.pipeline_id)

    def is_first_batch(self) -> bool:
        """True if no batches have been committed yet for this pipeline."""
        return self.state.get_last_committed_batch(self.pipeline_id) is None

    def history(self, limit: int = 10) -> list[dict]:
        """
        Return recent checkpoint history for this pipeline.
        Used by operator UI and health API.
        """
        all_keys = self.state.all_keys()
        checkpoint_keys = [
            k for k in all_keys
            if k.startswith(f"checkpoint#")
        ]

        checkpoints = []
        for key in checkpoint_keys:
            data = self.state.get(key)
            if data and data.get("pipeline_id") == self.pipeline_id:
                checkpoints.append(data)

        # Sort by checkpointed_at descending
        checkpoints.sort(
            key=lambda x: x.get("checkpointed_at", ""),
            reverse=True,
        )
        return checkpoints[:limit]