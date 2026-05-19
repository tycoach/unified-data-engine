-- dbt/models/marts/dim_npm_packages.sql
-- SCD Type 1 incremental model for NPM packages
-- Overwrites with latest package metadata on every batch
-- dbt generates adapter-appropriate MERGE/INSERT-UPDATE — zero custom SQL

{{
  config(
    materialized='incremental',
    unique_key='package_name',
    on_schema_change='sync_all_columns',
    schema='marts'
  )
}}

SELECT
    package_name,
    latest_version,
    description,
    author,
    license,
    weekly_downloads,
    total_versions,
    homepage,
    repository_url,
    keywords,
    updated_at,
    batch_id                    AS last_batch_id,
    _ingested_at                AS last_ingested_at

FROM {{ ref('npm_packages_staged') }}

{% if is_incremental() %}
-- Only process records newer than the last load
WHERE updated_at > (SELECT MAX(updated_at) FROM {{ this }})
{% endif %}