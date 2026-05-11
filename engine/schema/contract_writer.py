# engine/schema/contract_writer.py
# Auto-generates dbt source contracts from the locked schema registry
# MERGES into _sources.yml — never overwrites other pipelines' sources
# Called after lock() and after evolve()

import yaml
import logging
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DBT_SOURCES_PATH = Path("dbt/models/staging/_sources.yml")

UDE_TO_DBT_TYPE = {
    "string":   "varchar",
    "integer":  "int64",
    "float":    "float64",
    "boolean":  "bool",
    "date":     "date",
    "datetime": "timestamp",
}


def _build_table_entry(schema: dict) -> dict:
    """Build a single dbt source table entry from a locked schema."""
    pipeline_id = schema["pipeline_id"]
    version = schema["version"]
    locked_at = schema.get("locked_at", datetime.now(timezone.utc).isoformat())
    fields = schema["fields"]

    columns = []
    for field_name, field_meta in fields.items():
        dbt_type = UDE_TO_DBT_TYPE.get(field_meta["type"], "varchar")
        nullable = field_meta.get("nullable", True)

        col = {"name": field_name, "data_type": dbt_type}

        constraints = []
        if not nullable:
            constraints.append({"type": "not_null"})
        if field_name in ("customer_id", "order_id", "product_id"):
            constraints.append({"type": "unique"})
        if constraints:
            col["constraints"] = constraints

        columns.append(col)

    # Always include batch_id column
    columns.append({"name": "batch_id", "data_type": "varchar"})

    return {
        "name": f"{pipeline_id}_staged",
        "description": (
            f"{pipeline_id.capitalize()} source — "
            f"schema v{version} (locked {locked_at[:10]})"
        ),
        "config": {"contract": {"enforced": True}},
        "columns": columns,
    }


def write_contract(schema: dict):
    """
    Write/update the dbt source contract for one pipeline.
    Merges into the existing _sources.yml — other pipelines are preserved.
    """
    pipeline_id = schema["pipeline_id"]
    DBT_SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing _sources.yml or start fresh
    existing = {"version": 2, "sources": []}
    if DBT_SOURCES_PATH.exists():
        try:
            with open(DBT_SOURCES_PATH) as f:
                content = f.read()
                # Strip header comments before parsing
                yaml_content = "\n".join(
                    l for l in content.splitlines()
                    if not l.startswith("#")
                )
                loaded = yaml.safe_load(yaml_content)
                if loaded:
                    existing = loaded
        except Exception as e:
            logger.warning(f"[ContractWriter] Could not parse existing _sources.yml: {e}")

    # Find or create the staging source block
    sources = existing.get("sources", [])
    staging_source = next(
        (s for s in sources if s.get("name") == "staging"), None
    )

    if not staging_source:
        staging_source = {
            "name": "staging",
            "schema": "raw_staging",
            "tables": [],
        }
        sources.append(staging_source)

    existing["sources"] = sources

    # Build the new table entry for this pipeline
    new_table = _build_table_entry(schema)
    table_name = new_table["name"]

    # Replace existing entry for this pipeline or append
    tables = staging_source.get("tables", [])
    replaced = False
    for i, t in enumerate(tables):
        if t.get("name") == table_name:
            tables[i] = new_table
            replaced = True
            break

    if not replaced:
        tables.append(new_table)

    staging_source["tables"] = tables

    # Write back with header comment
    header = (
        f"# dbt/models/staging/_sources.yml\n"
        f"# AUTO-MANAGED by UDE schema registry\n"
        f"# Last updated: {datetime.now(timezone.utc).isoformat()}\n"
        f"# DO NOT EDIT columns manually — use make schema-sync\n\n"
    )

    with open(DBT_SOURCES_PATH, "w") as f:
        f.write(header)
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

    logger.info(
        f"[ContractWriter] ---- Updated dbt source contract for "
        f"'{pipeline_id}' v{schema['version']} → {DBT_SOURCES_PATH}"
    )


def read_contract() -> str | None:
    """Read current _sources.yml content."""
    if DBT_SOURCES_PATH.exists():
        return DBT_SOURCES_PATH.read_text()
    return None