# tests/unit/cli/test_scaffold.py
"""
Unit tests for cli/scaffold/pipeline.py and cli/scaffold/project.py

Tests cover:
  - pipeline YAML generation
  - staging model SQL generation
  - snapshot SQL generation (SCD Type 2)
  - incremental model SQL generation (SCD Type 1)
  - project skeleton directory structure
  - field type casting in generated SQL
  - overwrite=False guard (existing files not overwritten)

All tests use tmp_path — no writes to the real project.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.scaffold.pipeline import scaffold_pipeline
from cli.scaffold.project import scaffold_project


# ── Fixtures ──────────────────────────────────────────────────────────────────

CUSTOMERS_FIELDS = {
    "customer_id": {"type": "string",   "nullable": False},
    "email":       {"type": "string",   "nullable": True},
    "city":        {"type": "string",   "nullable": True},
    "country":     {"type": "string",   "nullable": True},
    "tier":        {"type": "string",   "nullable": False},
    "updated_at":  {"type": "datetime", "nullable": False},
}

PRODUCTS_FIELDS = {
    "product_id": {"type": "string",  "nullable": False},
    "sku":        {"type": "string",  "nullable": False},
    "price":      {"type": "float",   "nullable": False},
    "stock":      {"type": "integer", "nullable": True},
    "updated_at": {"type": "datetime","nullable": False},
}


def _scaffold_customers_type2(tmp_path: Path) -> None:
    scaffold_pipeline(
        pipeline_id="customers",
        natural_key="customer_id",
        scd_type=2,
        subscription_id="raw.customers-sub",
        null_threshold=0.05,
        late_arrival_window="24h",
        duplicate_window="30m",
        fields=CUSTOMERS_FIELDS,
        target_dir=tmp_path,
    )


def _scaffold_products_type1(tmp_path: Path) -> None:
    scaffold_pipeline(
        pipeline_id="products",
        natural_key="product_id",
        scd_type=1,
        subscription_id="raw.products-sub",
        null_threshold=0.02,
        late_arrival_window="12h",
        duplicate_window="15m",
        fields=PRODUCTS_FIELDS,
        target_dir=tmp_path,
    )


# ── Pipeline YAML ─────────────────────────────────────────────────────────────

class TestPipelineYAML:

    def test_yaml_file_created(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        assert (tmp_path / "config" / "pipelines" / "customers.yml").exists()

    def test_yaml_contains_pipeline_id(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "customers.yml").read_text()
        assert "pipeline_id: customers" in content

    def test_yaml_contains_natural_key(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "customers.yml").read_text()
        assert "natural_key: customer_id" in content

    def test_yaml_contains_subscription_id(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "customers.yml").read_text()
        assert "subscription_id: raw.customers-sub" in content

    def test_yaml_scd_type2_has_snapshot(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "customers.yml").read_text()
        assert "snapshot: customers_snapshot" in content

    def test_yaml_scd_type1_has_no_snapshot(self, tmp_path):
        _scaffold_products_type1(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "products.yml").read_text()
        assert "snapshot: null" in content

    def test_yaml_contains_all_fields(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "customers.yml").read_text()
        for field in CUSTOMERS_FIELDS:
            assert field in content

    def test_yaml_nullable_lowercase(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "customers.yml").read_text()
        # Python True/False must be lowercased to valid YAML true/false
        assert "True" not in content
        assert "False" not in content

    def test_yaml_null_threshold_value(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "config" / "pipelines" / "customers.yml").read_text()
        assert "0.05" in content

    def test_existing_yaml_not_overwritten(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        yaml_path = tmp_path / "config" / "pipelines" / "customers.yml"
        original = yaml_path.read_text()

        # Scaffold again — should not overwrite
        _scaffold_customers_type2(tmp_path)
        assert yaml_path.read_text() == original


# ── Staging model SQL ─────────────────────────────────────────────────────────

class TestStagingModel:

    def test_staging_file_created(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        assert (tmp_path / "dbt" / "models" / "staging" / "customers_staged.sql").exists()

    def test_staging_contains_source_ref(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "staging" / "customers_staged.sql").read_text()
        assert "customers_raw" in content

    def test_staging_contains_batch_id_filter(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "staging" / "customers_staged.sql").read_text()
        assert "batch_id" in content

    def test_staging_casts_datetime_fields(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "staging" / "customers_staged.sql").read_text()
        assert "cast(updated_at as timestamp)" in content

    def test_staging_casts_float_fields(self, tmp_path):
        _scaffold_products_type1(tmp_path)
        content = (tmp_path / "dbt" / "models" / "staging" / "products_staged.sql").read_text()
        assert "cast(price as float)" in content

    def test_staging_casts_integer_fields(self, tmp_path):
        _scaffold_products_type1(tmp_path)
        content = (tmp_path / "dbt" / "models" / "staging" / "products_staged.sql").read_text()
        assert "cast(stock as integer)" in content

    def test_staging_contains_all_fields(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "staging" / "customers_staged.sql").read_text()
        for field in CUSTOMERS_FIELDS:
            assert field in content


# ── Snapshot SQL (SCD Type 2) ─────────────────────────────────────────────────

class TestSnapshotSQL:

    def test_snapshot_file_created_for_type2(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        assert (tmp_path / "dbt" / "snapshots" / "customers_snapshot.sql").exists()

    def test_snapshot_file_not_created_for_type1(self, tmp_path):
        _scaffold_products_type1(tmp_path)
        assert not (tmp_path / "dbt" / "snapshots" / "products_snapshot.sql").exists()

    def test_snapshot_contains_unique_key(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "snapshots" / "customers_snapshot.sql").read_text()
        assert "customer_id" in content

    def test_snapshot_contains_snapshot_name(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "snapshots" / "customers_snapshot.sql").read_text()
        assert "customers_snapshot" in content

    def test_snapshot_references_staging_model(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "snapshots" / "customers_snapshot.sql").read_text()
        assert "customers_staged" in content

    def test_snapshot_contains_batch_id(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "snapshots" / "customers_snapshot.sql").read_text()
        assert "batch_id" in content

    def test_snapshot_contains_all_fields(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "snapshots" / "customers_snapshot.sql").read_text()
        for field in CUSTOMERS_FIELDS:
            assert field in content


# ── Incremental model SQL (SCD Type 1 + 2 marts) ─────────────────────────────

class TestIncrementalModel:

    def test_mart_file_created(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        assert (tmp_path / "dbt" / "models" / "marts" / "dim_customers.sql").exists()

    def test_mart_file_created_type1(self, tmp_path):
        _scaffold_products_type1(tmp_path)
        assert (tmp_path / "dbt" / "models" / "marts" / "dim_products.sql").exists()

    def test_mart_contains_unique_key(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "marts" / "dim_customers.sql").read_text()
        assert "customer_id" in content

    def test_mart_contains_incremental_config(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "marts" / "dim_customers.sql").read_text()
        assert "materialized='incremental'" in content

    def test_mart_contains_sync_all_columns(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "marts" / "dim_customers.sql").read_text()
        assert "sync_all_columns" in content

    def test_mart_contains_is_incremental_block(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "marts" / "dim_customers.sql").read_text()
        assert "is_incremental" in content

    def test_mart_references_staging_model(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "marts" / "dim_customers.sql").read_text()
        assert "customers_staged" in content

    def test_mart_contains_last_batch_id(self, tmp_path):
        _scaffold_customers_type2(tmp_path)
        content = (tmp_path / "dbt" / "models" / "marts" / "dim_customers.sql").read_text()
        assert "last_batch_id" in content


# ── Project skeleton (ude init) ───────────────────────────────────────────────

class TestProjectScaffold:

    def _run_init(self, tmp_path: Path) -> None:
        scaffold_project(
            target_dir=tmp_path,
            project_name="test-project",
            env="local",
            gcp_project="minisky-local",
        )

    def test_engine_yml_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "config" / "engine.yml").exists()

    def test_pipelines_dir_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "config" / "pipelines").is_dir()

    def test_dbt_project_yml_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "dbt" / "dbt_project.yml").exists()

    def test_dbt_profiles_yml_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "dbt" / "profiles.yml").exists()

    def test_dbt_packages_yml_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "dbt" / "packages.yml").exists()

    def test_sources_yml_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "dbt" / "models" / "staging" / "_sources.yml").exists()

    def test_docker_compose_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "docker-compose.yml").exists()

    def test_env_example_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / ".env.example").exists()

    def test_monitoring_prometheus_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / "monitoring" / "prometheus" / "prometheus.yml").exists()

    def test_engine_yml_contains_project_name(self, tmp_path):
        self._run_init(tmp_path)
        content = (tmp_path / "config" / "engine.yml").read_text()
        assert "test-project" in content

    def test_engine_yml_contains_gcp_project(self, tmp_path):
        self._run_init(tmp_path)
        content = (tmp_path / "config" / "engine.yml").read_text()
        assert "minisky-local" in content

    def test_engine_yml_local_env_has_emulator_host(self, tmp_path):
        self._run_init(tmp_path)
        content = (tmp_path / "config" / "engine.yml").read_text()
        assert "emulator_host" in content

    def test_profiles_yml_contains_gcp_project(self, tmp_path):
        self._run_init(tmp_path)
        content = (tmp_path / "dbt" / "profiles.yml").read_text()
        assert "minisky-local" in content

    def test_dbt_dir_structure_complete(self, tmp_path):
        self._run_init(tmp_path)
        expected_dirs = [
            tmp_path / "dbt" / "models" / "staging",
            tmp_path / "dbt" / "models" / "marts",
            tmp_path / "dbt" / "snapshots",
            tmp_path / "dbt" / "tests" / "generic",
            tmp_path / "dbt" / "tests" / "singular",
            tmp_path / "dbt" / "macros",
            tmp_path / "dbt" / "analyses",
        ]
        for d in expected_dirs:
            assert d.is_dir(), f"Missing directory: {d}"

    def test_gitignore_created(self, tmp_path):
        self._run_init(tmp_path)
        assert (tmp_path / ".gitignore").exists()

    def test_existing_gitignore_not_overwritten(self, tmp_path):
        existing = tmp_path / ".gitignore"
        existing.write_text("# custom gitignore\n")

        self._run_init(tmp_path)
        assert existing.read_text() == "# custom gitignore\n"