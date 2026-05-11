-- dbt/models/marts/fct_orders.sql
-- Incremental fact table for orders
-- Append-only — orders are immutable once created

{{
  config(
    materialized='incremental',
    unique_key='order_id',
    on_schema_change='sync_all_columns',
    schema='marts'
  )
}}

SELECT
    order_id,
    customer_id,
    amount,
    currency,
    status,
    created_at,
    batch_id                AS source_batch_id,
    _ingested_at

FROM {{ ref('orders_staged') }}

{% if is_incremental() %}
WHERE created_at > (SELECT MAX(created_at) FROM {{ this }})
{% endif %}