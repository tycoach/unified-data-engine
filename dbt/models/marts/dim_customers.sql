-- dbt/models/marts/dim_customers.sql
-- SCD Type 1 — overwrites on change
-- dbt generates adapter-appropriate MERGE/INSERT-UPDATE
-- Zero custom SQL in the engine

{{
  config(
    materialized='incremental',
    unique_key='customer_id',
    on_schema_change='sync_all_columns',
    schema='marts'
  )
}}

SELECT
    customer_id,
    email,
    city,
    country,
    tier,
    updated_at,
    batch_id                AS last_batch_id,
    _ingested_at            AS last_ingested_at

FROM {{ ref('customers_staged') }}

{% if is_incremental() %}
-- Only process records newer than last load
WHERE updated_at > (SELECT MAX(updated_at) FROM {{ this }})
{% endif %}