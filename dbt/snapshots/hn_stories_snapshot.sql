-- dbt/snapshots/hn_stories_snapshot.sql
-- SCD Type 2 snapshot for Hacker News stories
-- Tracks full history of score and comment count changes
-- HN stories churn fast — expect high snapshot open/close activity
-- dbt adds: dbt_scd_id, dbt_updated_at, dbt_valid_from, dbt_valid_to
-- Current records: WHERE dbt_valid_to IS NULL

{% snapshot hn_stories_snapshot %}

{{
  config(
    target_schema='snapshots',
    unique_key='story_id',
    strategy='timestamp',
    updated_at='updated_at',
    invalidate_hard_deletes=True,
  )
}}

SELECT
    story_id,
    title,
    author,
    url,
    score,
    num_comments,
    story_type,
    tags,
    updated_at,
    '{{ var("batch_id") }}' AS source_batch_id

FROM {{ source('staging', 'hn_stories_staged') }}

{% if var('batch_id', none) is not none %}
WHERE batch_id = '{{ var("batch_id") }}'
{% endif %}

{% endsnapshot %}