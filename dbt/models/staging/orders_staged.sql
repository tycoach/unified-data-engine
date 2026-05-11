-- dbt/models/staging/orders_staged.sql
-- Reads from raw_staging.orders_staged
-- Casts types, filters to current batch

{{
  config(
    materialized='view',
    schema='staging'
  )
}}

SELECT
    order_id,
    customer_id,
    CAST(amount AS DOUBLE) AS amount,
    currency,
    status,
    CAST(created_at AS TIMESTAMP) AS created_at,
    batch_id,
    _ingested_at

FROM {{ source('staging', 'orders_staged') }}

{% if var('batch_id', none) is not none %}
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}