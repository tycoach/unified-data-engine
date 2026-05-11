# engine/schema/inferencer.py
# Infers schema from a batch of records using Polars
# Called ONCE on first load — schema is then locked in the registry
# Never called again unless operator triggers a schema reset

import polars as pl
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Polars dtype → canonical UDE type mapping
POLARS_TO_UDE = {
    pl.Utf8: "string",
    pl.String: "string",
    pl.Int32: "integer",
    pl.Int64: "integer",
    pl.Float32: "float",
    pl.Float64: "float",
    pl.Boolean: "boolean",
    pl.Date: "date",
    pl.Datetime: "datetime",
    pl.Duration: "string",
    pl.List: "string",
    pl.Null: "string",
}


def infer_schema(records: list[dict], pipeline_id: str) -> dict:
    """
    Infer schema from a list of record dicts using Polars.
    """
    if not records:
        raise ValueError(f"[Inferencer] Cannot infer schema from empty batch.")

    # Strip internal meta fields added by consumer
    clean_records = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in records
    ]

    logger.info(
        f"[Inferencer] Inferring schema for '{pipeline_id}' "
        f"from {len(clean_records)} records..."
    )

    df = pl.DataFrame(clean_records, infer_schema_length=len(clean_records))

    fields = {}
    for col_name, dtype in zip(df.columns, df.dtypes):
        ude_type = _map_dtype(dtype)
        null_count = df[col_name].null_count()
        nullable = null_count > 0

        fields[col_name] = {
            "type": ude_type,
            "nullable": nullable,
        }

        logger.debug(
            f"[Inferencer]   {col_name}: {dtype} → {ude_type} "
            f"(nullable={nullable})"
        )

    schema = {
        "pipeline_id": pipeline_id,
        "version": 1,
        "inferred_at": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
    }

    logger.info(
        f"[Inferencer] Schema inferred: {len(fields)} fields — "
        f"{list(fields.keys())}"
    )

    return schema


def _map_dtype(dtype) -> str:
    """Map a Polars dtype to a UDE canonical type string."""
    # Check direct match first
    for polars_type, ude_type in POLARS_TO_UDE.items():
        if dtype == polars_type:
            return ude_type

    # Check base type for parameterized types (e.g. Datetime(time_unit=...))
    dtype_str = str(dtype).lower()
    if "datetime" in dtype_str:
        return "datetime"
    if "date" in dtype_str:
        return "date"
    if "int" in dtype_str:
        return "integer"
    if "float" in dtype_str:
        return "float"
    if "bool" in dtype_str:
        return "boolean"
    if "str" in dtype_str or "utf" in dtype_str:
        return "string"

    logger.warning(f"[Inferencer] Unknown dtype '{dtype}' — defaulting to string")
    return "string"