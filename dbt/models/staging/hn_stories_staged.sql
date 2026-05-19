-- dbt/models/staging/hn_stories_staged.sql
-- Reads from raw_staging.hn_stories_staged
-- Casts types, renames columns, filters to current batch only
-- Source for hn_stories_snapshot (SCD Type 2)

{{
  config(
    materialized='view',
    schema='staging'
  )
}}

SELECT
    story_id,
    title,
    author,
    url,
    CAST(score        AS INTEGER)   AS score,
    CAST(num_comments AS INTEGER)   AS num_comments,
    story_type,
    tags,
    CAST(updated_at   AS TIMESTAMP) AS updated_at,
    batch_id,
    _ingested_at

FROM {{ source('staging', 'hn_stories_staged') }}

{% if var('batch_id', none) is not none %}
-- Filter to current batch only
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}