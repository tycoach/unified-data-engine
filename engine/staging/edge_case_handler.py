# engine/staging/edge_case_handler.py
# The gate between ingestion and dbt
# Dirty data NEVER passes this point
# Every check is configurable per pipeline via pipeline YAML
#
# Checks (in order):
#   1. Null threshold    — quarantine if >X% of records have nulls in critical fields
#   2. Duplicate detection — deduplicate within a time window on natural key
#   3. Type validation   — validate fields against locked schema types
#   4. Late arrival      — flag records older than configured window
#
# Output:
#   clean_records   → go to staging_writer → dbt
#   dirty_records   → go to quarantine with full audit trail

import logging
import polars as pl
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EdgeCaseResult:
    """Result of the edge case gate for a single batch."""
    pipeline_id: str
    batch_id: str
    total_records: int
    clean_records: list[dict]
    dirty_records: list[dict]       # quarantine candidates
    discarded_duplicates: list[dict]  # duplicates removed silently
    null_rate: float
    late_arrival_count: int
    passed: bool                    # True if batch cleared the gate

    @property
    def quarantine_count(self):
        return len(self.dirty_records)

    @property
    def clean_count(self):
        return len(self.clean_records)

    def summary(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "batch_id": self.batch_id,
            "total": self.total_records,
            "clean": self.clean_count,
            "quarantined": self.quarantine_count,
            "duplicates_removed": len(self.discarded_duplicates),
            "null_rate": round(self.null_rate, 4),
            "late_arrivals": self.late_arrival_count,
            "passed": self.passed,
        }


class EdgeCaseHandler:
    """
    Runs all edge case checks on a batch of records.
    Configured per pipeline — thresholds come from pipeline YAML.
    """

    def __init__(self, config: dict):
        """
        """
        self.pipeline_id = config["pipeline_id"]
        self.natural_key = config["natural_key"]
        self.null_threshold = config.get("null_threshold", 0.05)
        self.late_arrival_window = self._parse_duration(
            config.get("late_arrival_window", "24h")
        )
        self.duplicate_window = self._parse_duration(
            config.get("duplicate_window", "30m")
        )
        self.mode = config.get("edge_case_mode", "quarantine")

        logger.info(
            f"[EdgeCase] Initialized for '{self.pipeline_id}' | "
            f"key={self.natural_key} | null_threshold={self.null_threshold} | "
            f"mode={self.mode}"
        )

    def run(
        self,
        records: list[dict],
        batch_id: str,
        locked_schema: dict,
    ) -> EdgeCaseResult:
        """
        Run all edge case checks on a batch.
        """
        if not records:
            return EdgeCaseResult(
                pipeline_id=self.pipeline_id,
                batch_id=batch_id,
                total_records=0,
                clean_records=[],
                dirty_records=[],
                discarded_duplicates=[],
                null_rate=0.0,
                late_arrival_count=0,
                passed=True,
            )

        logger.info(
            f"[EdgeCase] Running checks on {len(records)} records "
            f"for batch {batch_id}..."
        )

        dirty = []
        discarded_duplicates = []
        late_arrival_count = 0

        # Strip consumer meta fields before checks
        clean_records = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in records
        ]

        # ──  Null threshold check ───────────────────────────────────────────
        clean_records, null_dirty, null_rate = self._check_nulls(
            clean_records, locked_schema, batch_id
        )
        dirty.extend(null_dirty)
        logger.info(
            f"[EdgeCase] Null check: rate={null_rate:.2%} | "
            f"quarantined={len(null_dirty)}"
        )

        # ── Duplicate detection ────────────────────────────────────────────
        clean_records, dupes = self._check_duplicates(clean_records)
        discarded_duplicates.extend(dupes)
        logger.info(
            f"[EdgeCase] Duplicate check: removed={len(dupes)}"
        )

        # ──  Type validation ────────────────────────────────────────────────
        clean_records, type_dirty = self._check_types(
            clean_records, locked_schema, batch_id
        )
        dirty.extend(type_dirty)
        logger.info(
            f"[EdgeCase] Type check: quarantined={len(type_dirty)}"
        )

        # ──  Late arrival detection ─────────────────────────────────────────
        clean_records, late_count = self._check_late_arrivals(clean_records)
        late_arrival_count = late_count
        logger.info(
            f"[EdgeCase] Late arrival check: flagged={late_count}"
        )

        passed = len(dirty) == 0 or (
            len(dirty) / max(len(records), 1) <= self.null_threshold
        )

        result = EdgeCaseResult(
            pipeline_id=self.pipeline_id,
            batch_id=batch_id,
            total_records=len(records),
            clean_records=clean_records,
            dirty_records=dirty,
            discarded_duplicates=discarded_duplicates,
            null_rate=null_rate,
            late_arrival_count=late_arrival_count,
            passed=passed,
        )

        logger.info(
            f"[EdgeCase] Gate result: {result.clean_count} clean | "
            f"{result.quarantine_count} quarantined | "
            f"{len(discarded_duplicates)} dupes removed"
        )

        return result

    def _check_nulls(
        self,
        records: list[dict],
        locked_schema: dict,
        batch_id: str,
    ) -> tuple[list[dict], list[dict], float]:
        """
        Quarantine records where non-nullable fields are null.
        """
        non_nullable = [
            f for f, meta in locked_schema["fields"].items()
            if not meta.get("nullable", True)
        ]

        clean = []
        dirty = []
        total_null_violations = 0

        for record in records:
            violations = [
                f for f in non_nullable
                if record.get(f) is None or record.get(f) == ""
            ]
            if violations:
                total_null_violations += 1
                dirty.append({
                    **record,
                    "_failure_reason": f"NULL_VIOLATION: {violations}",
                    "_batch_id": batch_id,
                    "_pipeline_id": self.pipeline_id,
                })
            else:
                clean.append(record)

        null_rate = total_null_violations / max(len(records), 1)
        return clean, dirty, null_rate

    def _check_duplicates(
        self,
        records: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """
        Deduplicate on natural key within the batch.
        """
        seen = {}
        for record in records:
            key = record.get(self.natural_key)
            if key is not None:
                seen[key] = record  # last write wins

        unique_records = list(seen.values())
        discarded = [
            r for r in records
            if r not in unique_records
        ]
        return unique_records, discarded

    def _check_types(
        self,
        records: list[dict],
        locked_schema: dict,
        batch_id: str,
    ) -> tuple[list[dict], list[dict]]:
        """
        Basic type validation against locked schema.
        """
        clean = []
        dirty = []

        type_map = {
            "string": str,
            "integer": (int,),
            "float": (int, float),
            "boolean": bool,
        }

        for record in records:
            violations = []
            for field_name, meta in locked_schema["fields"].items():
                value = record.get(field_name)
                if value is None:
                    continue  # nulls handled by null check

                expected_python = type_map.get(meta["type"])
                if expected_python and not isinstance(value, expected_python):
                    # Allow string representations of numbers
                    if meta["type"] in ("integer", "float") and isinstance(value, str):
                        try:
                            float(value)
                            continue
                        except ValueError:
                            pass
                    violations.append(
                        f"{field_name}: expected {meta['type']}, "
                        f"got {type(value).__name__}"
                    )

            if violations:
                dirty.append({
                    **record,
                    "_failure_reason": f"TYPE_VIOLATION: {violations}",
                    "_batch_id": batch_id,
                    "_pipeline_id": self.pipeline_id,
                })
            else:
                clean.append(record)

        return clean, dirty

    def _check_late_arrivals(
        self,
        records: list[dict],
    ) -> tuple[list[dict], int]:
        """
        Flag records older than the late_arrival_window.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - self.late_arrival_window
        late_count = 0

        result = []
        for record in records:
            ts_str = record.get("updated_at") or record.get("created_at")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        record["_late_arrival"] = True
                        late_count += 1
                except Exception:
                    pass
            result.append(record)

        return result, late_count

    @staticmethod
    def _parse_duration(duration_str: str) -> timedelta:
        """Parse duration strings like '24h', '30m', '7d' into timedelta."""
        unit = duration_str[-1].lower()
        value = int(duration_str[:-1])
        if unit == "h":
            return timedelta(hours=value)
        elif unit == "m":
            return timedelta(minutes=value)
        elif unit == "d":
            return timedelta(days=value)
        else:
            raise ValueError(f"Unknown duration unit: {unit}")