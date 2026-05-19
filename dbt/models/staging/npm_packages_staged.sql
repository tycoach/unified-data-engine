-- dbt/models/staging/npm_packages_staged.sql
-- Reads from raw_staging.npm_packages_staged
-- Casts types, renames columns, filters to current batch only
-- Source for dim_npm_packages incremental model (SCD Type 1)

{{
  config(
    materialized='view',
    schema='staging'
  )
}}

SELECT
    package_name,
    latest_version,
    description,
    author,
    license,
    CAST(weekly_downloads AS INTEGER) AS weekly_downloads,
    CAST(total_versions   AS INTEGER) AS total_versions,
    homepage,
    repository_url,
    keywords,
    CAST(updated_at AS TIMESTAMP) AS updated_at,
    batch_id,
    _ingested_at

FROM {{ source('staging', 'npm_packages_staged') }}

{% if var('batch_id', none) is not none %}
-- Filter to current batch only
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}