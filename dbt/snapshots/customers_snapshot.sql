-- dbt/snapshots/customers_snapshot.sql
-- SCD Type 2 — full history preserved
-- dbt handles: open/close logic, dbt_valid_from, dbt_valid_to, atomicity
-- The engine's v1 equivalent was ~80 lines of Python + SQL
-- This is 10 lines of declaration

{% snapshot customers_snapshot %}

{{
  config(
    target_schema='snapshots',
    unique_key='customer_id',
    strategy='timestamp',
    updated_at='updated_at',
    invalidate_hard_deletes=True,
  )
}}

SELECT
    customer_id,
    email,
    city,
    country,
    tier,
    updated_at,
    batch_id                        AS source_batch_id

FROM {{ ref('customers_staged') }}

{% endsnapshot %}

-- dbt automatically adds:
--   dbt_scd_id      — surrogate key for each snapshot row
--   dbt_updated_at  — when this row was last processed
--   dbt_valid_from  — when this version became active
--   dbt_valid_to    — when this version was superseded (NULL = current)
--
-- Query current records: WHERE dbt_valid_to IS NULL
-- Query history:         WHERE customer_id = 'C-0001' ORDER BY dbt_valid_from