-- dbt/models/staging/products_staged.sql
-- Reads from raw_staging.products_staged
-- Casts types, filters to current batch

{{
  config(
    materialized='view',
    schema='staging'
  )
}}

SELECT
    product_id,
    sku,
    name,
    category,
    CAST(price AS DOUBLE)           AS price,
    CAST(in_stock AS BOOLEAN)       AS in_stock,
    CAST(updated_at AS TIMESTAMP)   AS updated_at,
    batch_id,
    _ingested_at

FROM {{ source('staging', 'products_staged') }}

{% if var('batch_id', none) is not none %}
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}