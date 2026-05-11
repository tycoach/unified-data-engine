-- dbt/models/staging/customers_staged.sql
-- Reads from raw_staging.customers_staged
-- Casts types, renames columns, filters to current batch only
-- This is the dbt source for both snapshot and incremental models

{{
  config(
    materialized='view',
    schema='staging'
  )
}}

SELECT
    customer_id,
    email,
    city,
    country,
    tier,
    CAST(updated_at AS TIMESTAMP) AS updated_at,
    batch_id,
    _ingested_at

FROM {{ source('staging', 'customers_staged') }}

{% if var('batch_id', none) is not none %}
-- Filter to current batch only — critical for performance at scale
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}