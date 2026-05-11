# engine/schema/deviation.py
# Compares incoming batch schema against locked schema
# Three outcomes: MATCH | EVOLVED | BROKEN
# This is the intelligence layer — determines how each batch is handled

import logging
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DeviationResult:
    """Result of a schema deviation check."""
    status: str           # MATCH | EVOLVED | BROKEN
    pipeline_id: str
    locked_version: int
    details: list[str]    # human-readable description of what changed
    updated_fields: dict  # only populated for EVOLVED — merged field set


def check_deviation(
    pipeline_id: str,
    locked_schema: dict,
    incoming_fields: dict,
) -> DeviationResult:
    """
    Compare incoming batch fields against the locked schema.
    """
    locked_fields = locked_schema["fields"]
    locked_version = locked_schema["version"]
    details = []
    evolved = False
    broken = False
    updated_fields = dict(locked_fields)  # start from locked, apply safe changes

    locked_cols = set(locked_fields.keys())
    incoming_cols = set(incoming_fields.keys())

    # ── Removed columns → BROKEN ─────────────────────────────────────────────
    removed = locked_cols - incoming_cols
    for col in removed:
        details.append(f"BROKEN: column '{col}' removed from source")
        broken = True

    # ── New columns → EVOLVED ────────────────────────────────────────────────
    added = incoming_cols - locked_cols
    for col in added:
        updated_fields[col] = incoming_fields[col]
        updated_fields[col]["nullable"] = True  # new columns are nullable by default
        details.append(
            f"EVOLVED: new column '{col}' "
            f"({incoming_fields[col]['type']}, nullable=True)"
        )
        evolved = True

    # ── Existing columns — type and nullable checks ───────────────────────────
    for col in locked_cols & incoming_cols:
        locked_type = locked_fields[col]["type"]
        incoming_type = incoming_fields[col]["type"]
        locked_nullable = locked_fields[col]["nullable"]
        incoming_nullable = incoming_fields[col]["nullable"]

        # Type change check
        if locked_type != incoming_type:
            if _is_type_widening(locked_type, incoming_type):
                updated_fields[col]["type"] = incoming_type
                details.append(
                    f"EVOLVED: column '{col}' type widened "
                    f"{locked_type} → {incoming_type}"
                )
                evolved = True
            else:
                details.append(
                    f"BROKEN: column '{col}' type incompatible "
                    f"{locked_type} → {incoming_type}"
                )
                broken = True

        # Nullable change — becoming nullable is safe, becoming non-nullable is not
        if not locked_nullable and incoming_nullable:
            updated_fields[col]["nullable"] = True
            details.append(
                f"EVOLVED: column '{col}' became nullable"
            )
            evolved = True

    # ── Determine final status ────────────────────────────────────────────────
    if broken:
        status = "BROKEN"
    elif evolved:
        status = "EVOLVED"
    else:
        status = "MATCH"

    result = DeviationResult(
        status=status,
        pipeline_id=pipeline_id,
        locked_version=locked_version,
        details=details,
        updated_fields=updated_fields if status == "EVOLVED" else {},
    )

    _log_result(result)
    return result


def _is_type_widening(from_type: str, to_type: str) -> bool:
    """
    Returns True if the type change is a safe widening.
    """
    safe_widenings = {
        ("integer", "float"),
        ("integer", "string"),
        ("float", "string"),
        ("date", "datetime"),
        ("date", "string"),
        ("datetime", "string"),
        ("boolean", "string"),
        ("boolean", "integer"),
    }
    return (from_type, to_type) in safe_widenings


def _log_result(result: DeviationResult):
    prefix = f"[Deviation] '{result.pipeline_id}' v{result.locked_version}"

    if result.status == "MATCH":
        logger.info(f"{prefix} → MATCH ")

    elif result.status == "EVOLVED":
        logger.info(f"{prefix} → EVOLVED ")
        for detail in result.details:
            logger.info(f"  {detail}")

    elif result.status == "BROKEN":
        logger.error(f"{prefix} → BROKEN ")
        for detail in result.details:
            logger.error(f"  {detail}")