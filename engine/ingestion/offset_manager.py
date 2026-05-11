# engine/ingestion/offset_manager.py
# Tracks batch lifecycle — batch IDs flow through to dbt as --vars
# Real offset management is handled by Pub/Sub ack/nack in consumer.py
# This layer provides traceability: every record carries its batch_id

import uuid
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BatchRecord:
    """Represents a single micro-batch lifecycle."""

    def __init__(self, pipeline_id: str):
        self.batch_id = str(uuid.uuid4())
        self.pipeline_id = pipeline_id
        self.opened_at = datetime.utcnow().isoformat()
        self.closed_at = None
        self.record_count = 0
        self.status = "OPEN"  # OPEN | COMPLETE | FAILED

    def close(self, record_count: int, status: str = "COMPLETE"):
        self.closed_at = datetime.utcnow().isoformat()
        self.record_count = record_count
        self.status = status

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "pipeline_id": self.pipeline_id,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "record_count": self.record_count,
            "status": self.status,
        }


class OffsetManager:
    """
    Manages batch lifecycle and ID generation.
    """

    def __init__(self, pipeline_id: str):
        self.pipeline_id = pipeline_id
        self.current_batch: BatchRecord = None
        self._history: list[BatchRecord] = []
        logger.info(f"[OffsetManager] Initialized for pipeline: {pipeline_id}")

    def open_batch(self) -> str:
        """Open a new batch. Returns batch_id for dbt vars."""
        self.current_batch = BatchRecord(self.pipeline_id)
        logger.info(f"[OffsetManager] Opened batch: {self.current_batch.batch_id}")
        return self.current_batch.batch_id

    def complete_batch(self, record_count: int):
        """Mark complete after dbt tests pass + checkpoint written."""
        if self.current_batch:
            self.current_batch.close(record_count, "COMPLETE")
            self._history.append(self.current_batch)
            logger.info(
                f"[OffsetManager] Batch {self.current_batch.batch_id} "
                f"COMPLETE ({record_count} records)"
            )

    def fail_batch(self, record_count: int = 0):
        """Mark failed — triggers nack, messages redelivered next cycle."""
        if self.current_batch:
            self.current_batch.close(record_count, "FAILED")
            self._history.append(self.current_batch)
            logger.warning(
                f"[OffsetManager] Batch {self.current_batch.batch_id} FAILED"
            )

    def current_batch_id(self) -> str:
        return self.current_batch.batch_id if self.current_batch else None

    def history(self) -> list[dict]:
        return [b.to_dict() for b in self._history]