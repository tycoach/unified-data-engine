# dbt/seed_duckdb.py
# Seeds DuckDB with staging data so dbt dev target can run
# Must be run before dbt run/test in dev environment
# In production this is replaced by real BigQuery on MiniSky
#
# Run: python dbt/seed_duckdb.py
# Or:  make dbt-seed-db

import duckdb

DB_PATH = "/tmp/unified_data_engine_dev.duckdb"
BATCH_ID = "seed-batch-dev-001"


def seed():
    con = duckdb.connect(DB_PATH)
    print(f"Seeding DuckDB at {DB_PATH}...")

    # ── Create schemas ────────────────────────────────────────────────────────
    for schema in ["raw_staging", "staging", "marts", "snapshots"]:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # ── customers_staged ─────────────────────────────────────────────────────
    con.execute("""
    CREATE TABLE IF NOT EXISTS raw_staging.customers_staged (
        customer_id  VARCHAR,
        email        VARCHAR,
        city         VARCHAR,
        country      VARCHAR,
        tier         VARCHAR,
        updated_at   VARCHAR,
        batch_id     VARCHAR,
        _ingested_at VARCHAR
    )
    """)

    con.execute("DELETE FROM raw_staging.customers_staged")
    customers = [
        ("C-0001", "u1@test.com", "Lagos",  "NG", "free",       "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
        ("C-0002", "u2@test.com", "London", "UK", "pro",        "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
        ("C-0003", "u3@test.com", "Abuja",  "NG", "enterprise", "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
    ]
    con.executemany(
        "INSERT INTO raw_staging.customers_staged VALUES (?,?,?,?,?,?,?,?)",
        customers,
    )
    count = con.execute("SELECT COUNT(*) FROM raw_staging.customers_staged").fetchone()[0]
    print(f"  raw_staging.customers_staged: {count} rows")

    # ── orders_staged ─────────────────────────────────────────────────────────
    con.execute("""
    CREATE TABLE IF NOT EXISTS raw_staging.orders_staged (
        order_id     VARCHAR,
        customer_id  VARCHAR,
        amount       DOUBLE,
        currency     VARCHAR,
        status       VARCHAR,
        created_at   VARCHAR,
        batch_id     VARCHAR,
        _ingested_at VARCHAR
    )
    """)

    con.execute("DELETE FROM raw_staging.orders_staged")
    orders = [
        ("O-000001", "C-0001", 150.00, "USD", "confirmed", "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
        ("O-000002", "C-0002", 299.99, "USD", "shipped",   "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
        ("O-000003", "C-0003", 899.00, "USD", "pending",   "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00"),
    ]
    con.executemany(
        "INSERT INTO raw_staging.orders_staged VALUES (?,?,?,?,?,?,?,?)",
        orders,
    )
    count = con.execute("SELECT COUNT(*) FROM raw_staging.orders_staged").fetchone()[0]
    print(f"   raw_staging.orders_staged: {count} rows")

    # ── products_staged ───────────────────────────────────────────────────────
    con.execute("""
    CREATE TABLE IF NOT EXISTS raw_staging.products_staged (
        product_id   VARCHAR,
        sku          VARCHAR,
        name         VARCHAR,
        category     VARCHAR,
        price        DOUBLE,
        in_stock     BOOLEAN,
        updated_at   VARCHAR,
        batch_id     VARCHAR,
        _ingested_at VARCHAR
    )
    """)

    con.execute("DELETE FROM raw_staging.products_staged")
    products = [
        (f"P-{i:04d}", f"SKU-{i:06d}", f"Product {i}", "Electronics",
         round(9.99 * i, 2), True, "2026-05-10T20:00:00", BATCH_ID, "2026-05-10T20:00:00")
        for i in range(1, 31)
    ]
    con.executemany(
        "INSERT INTO raw_staging.products_staged VALUES (?,?,?,?,?,?,?,?,?)",
        products,
    )
    count = con.execute("SELECT COUNT(*) FROM raw_staging.products_staged").fetchone()[0]
    print(f"   raw_staging.products_staged: {count} rows")

    con.close()
    print(" DuckDB seeded successfully")


if __name__ == "__main__":
    seed()