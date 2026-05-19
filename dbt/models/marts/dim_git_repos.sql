-- dbt/models/marts/dim_git_repos.sql
-- SCD Type 1 incremental model for GitHub repos
-- Overwrites with latest repo metadata on every batch

{{
  config(
    materialized='incremental',
    unique_key='repo_full_name',
    on_schema_change='sync_all_columns',
    schema='marts'
  )
}}

SELECT
    repo_full_name,
    repo_name,
    owner,
    description,
    stars,
    forks,
    open_issues,
    watchers,
    language,
    topics,
    is_archived,
    updated_at,
    batch_id        AS last_batch_id,
    _ingested_at    AS last_ingested_at

FROM {{ ref('git_repos_staged') }}

{% if is_incremental() %}
WHERE updated_at > (SELECT MAX(updated_at) FROM {{ this }})
{% endif %}
