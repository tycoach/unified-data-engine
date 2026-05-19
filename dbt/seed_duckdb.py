# dbt/seed_duckdb.py
# Seeds DuckDB with staging tables for all registered pipelines.
# Must run before dbt run/test in dev environment.
# Called automatically by: make up → [3/6] Seeding DuckDB
#
# Behaviour:
#   - Creates raw_staging schema if missing
#   - For each pipeline in config/pipelines/*.yml + API-registered:
#       creates raw_staging.{pipeline_id}_staged if it doesn't exist
#       seeds with sample rows for filesystem pipelines
#   - Safe to run multiple times (idempotent)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import duckdb
import logging

logging.basicConfig(level=logging.WARNING)

DB_PATH  = "/tmp/unified_data_engine_dev.duckdb"
BATCH_ID = "seed-batch-dev-001"

# ── Type mapping ──────────────────────────────────────────────────────────────
_TYPE_MAP = {
    "string":   "VARCHAR",
    "float":    "DOUBLE",
    "integer":  "INTEGER",
    "boolean":  "BOOLEAN",
    "datetime": "VARCHAR",
    "date":     "VARCHAR",
}

# ── Sample seed data for known filesystem pipelines ───────────────────────────
_SEED_DATA = {
    "customers": {
        "cols": ["customer_id", "email", "city", "country", "tier", "updated_at", "batch_id", "_ingested_at"],
        "rows": [
            ("C-0001", "u1@test.com", "Lagos",  "NG", "free",       "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
            ("C-0002", "u2@test.com", "London", "UK", "pro",        "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
            ("C-0003", "u3@test.com", "Abuja",  "NG", "enterprise", "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
        ],
    },
    "orders": {
        "cols": ["order_id", "customer_id", "amount", "currency", "status", "created_at", "batch_id", "_ingested_at"],
        "rows": [
            ("O-000001", "C-0001", 150.00, "USD", "confirmed", "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
            ("O-000002", "C-0002", 299.99, "USD", "shipped",   "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
            ("O-000003", "C-0003", 899.00, "USD", "pending",   "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
        ],
    },
    "products": {
        "cols": ["product_id", "sku", "name", "category", "price", "in_stock", "updated_at", "batch_id", "_ingested_at"],
        "rows": [
            (f"P-{i:04d}", f"SKU-{i:06d}", f"Product {i}", "Electronics",
             round(9.99 * i, 2), True, "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00")
            for i in range(1, 31)
        ],
    },
}


def _build_ddl(pipeline_id: str, fields: dict) -> str:
    """Build CREATE TABLE DDL from pipeline field definitions."""
    cols = []
    for fname, fdef in fields.items():
        dtype = _TYPE_MAP.get(fdef.get("type", "string"), "VARCHAR")
        cols.append(f"{fname} {dtype}")
    cols.append("batch_id VARCHAR")
    cols.append("_ingested_at VARCHAR")
    return f"CREATE TABLE IF NOT EXISTS raw_staging.{pipeline_id}_staged ({', '.join(cols)})"


def seed():
    from config.loader import load_pipelines

    con = duckdb.connect(DB_PATH)
    print(f"Seeding DuckDB at {DB_PATH}...")

    # Create all schemas
    for schema in ["raw_staging", "staging", "marts", "snapshots"]:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # Load all pipelines (filesystem + API-registered)
    pipelines = load_pipelines(project_token="")

    # Deduplicate by pipeline_id (filesystem takes precedence)
    seen = {}
    for p in pipelines:
        pid = p["pipeline_id"]
        if pid not in seen:
            seen[pid] = p

    for pid, p in seen.items():
        fields = p.get("fields", {})
        table  = f"raw_staging.{pid}_staged"

        if not fields:
            # Create minimal table with just batch_id
            try:
                con.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        batch_id     VARCHAR,
                        _ingested_at VARCHAR
                    )
                """)
                count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"  ✅ {table}: {count} rows (no fields defined)")
            except Exception as e:
                print(f"  ❌ {table}: {e}")
            continue

        # Create table from field definitions
        try:
            ddl = _build_ddl(pid, fields)
            con.execute(ddl)
        except Exception as e:
            print(f"  ❌ {table} DDL: {e}")
            continue

        # Seed with sample data for known filesystem pipelines
        if pid in _SEED_DATA:
            seed_info = _SEED_DATA[pid]
            try:
                con.execute(f"DELETE FROM {table}")
                placeholders = ", ".join(["?" for _ in seed_info["cols"]])
                col_list     = ", ".join(seed_info["cols"])
                con.executemany(
                    f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                    seed_info["rows"],
                )
            except Exception as e:
                print(f"  ⚠️  {table} seed data: {e}")

        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  ✅ {table}: {count} rows")

    con.close()
    print("✅ DuckDB seeded successfully")


if __name__ == "__main__":
    seed()