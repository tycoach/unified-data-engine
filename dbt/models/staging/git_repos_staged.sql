-- dbt/models/staging/git_repos_staged.sql
-- Reads from raw_staging.git_repos_staged
-- Casts types, renames columns, filters to current batch only
-- Source for both git_repos_snapshot (SCD Type 2)

{{
  config(
    materialized='view',
    schema='staging'
  )
}}

SELECT
    repo_full_name,
    repo_name,
    owner,
    description,
    CAST(stars       AS INTEGER)   AS stars,
    CAST(forks       AS INTEGER)   AS forks,
    CAST(open_issues AS INTEGER)   AS open_issues,
    CAST(watchers    AS INTEGER)   AS watchers,
    language,
    topics,
    CAST(is_archived AS BOOLEAN)   AS is_archived,
    CAST(updated_at  AS TIMESTAMP) AS updated_at,
    batch_id,
    _ingested_at

FROM {{ source('staging', 'git_repos_staged') }}

{% if var('batch_id', none) is not none %}
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}
