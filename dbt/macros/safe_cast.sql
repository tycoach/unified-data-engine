-- dbt/macros/safe_cast.sql
-- Type-safe casting macro
-- Returns NULL instead of erroring on bad cast
-- Used in staging models to handle EVOLVED type changes gracefully

{% macro safe_cast(column, type) %}
    CASE
        WHEN {{ column }} IS NULL THEN NULL
        ELSE TRY_CAST({{ column }} AS {{ type }})
    END
{% endmacro %}