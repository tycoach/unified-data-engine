-- dbt/models/marts/dim_products.sql
-- SCD Type 1 — overwrites on change
-- Latest product state only

{{
  config(
    materialized='incremental',
    unique_key='product_id',
    on_schema_change='sync_all_columns',
    schema='marts'
  )
}}

SELECT
    product_id,
    sku,
    name,
    category,
    price,
    in_stock,
    updated_at,
    batch_id            AS last_batch_id,
    _ingested_at        AS last_ingested_at

FROM {{ ref('products_staged') }}

{% if is_incremental() %}
WHERE updated_at > (SELECT MAX(updated_at) FROM {{ this }})
{% endif %}