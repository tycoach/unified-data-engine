-- dbt/snapshots/git_repos_snapshot.sql
-- SCD Type 2 snapshot for GitHub repositories
-- Tracks full history of stars, forks, open_issues changes over time
-- dbt adds: dbt_scd_id, dbt_updated_at, dbt_valid_from, dbt_valid_to
-- Current records: WHERE dbt_valid_to IS NULL

{% snapshot git_repos_snapshot %}

{{
  config(
    target_schema='snapshots',
    unique_key='repo_full_name',
    strategy='timestamp',
    updated_at='updated_at',
    invalidate_hard_deletes=True,
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
    '{{ var("batch_id") }}' AS source_batch_id

FROM {{ source('staging', 'git_repos_staged') }}

{% if var('batch_id', none) is not none %}
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}

{% endsnapshot %}
