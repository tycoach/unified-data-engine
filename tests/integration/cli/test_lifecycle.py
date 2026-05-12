# tests/integration/cli/test_lifecycle.py
"""
Integration tests for ude lifecycle commands.

These tests run against a live UDE stack (engine + API + MiniSky).
They are skipped automatically when the stack is not running — never
fail a CI build due to infrastructure not being present.

To run locally:
    ude up                              # start the stack
    pytest tests/integration/cli/ -v   # run integration tests

Marks:
    @pytest.mark.integration   — all tests in this file
    @pytest.mark.skipif        — skipped when API unreachable
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.main import app
from cli.core.checks import stack_is_running, minisky_is_alive
from cli.core.config import load_config

runner = CliRunner()
cfg    = load_config()

# Skip the entire module if the stack is not running
pytestmark = pytest.mark.skipif(
    not stack_is_running(cfg),
    reason="UDE stack not running — start with: ude up",
)


# ── ude status ────────────────────────────────────────────────────────────────

class TestStatus:

    def test_status_exits_zero(self):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0

    def test_status_shows_api_stack(self):
        result = runner.invoke(app, ["status"])
        assert "API stack" in result.output

    def test_status_shows_minisky(self):
        result = runner.invoke(app, ["status"])
        assert "MiniSky" in result.output

    def test_status_shows_dbt(self):
        result = runner.invoke(app, ["status"])
        assert "dbt" in result.output

    def test_status_shows_grafana(self):
        result = runner.invoke(app, ["status"])
        assert "Grafana" in result.output


# ── ude (no args — welcome panel) ────────────────────────────────────────────

class TestRootCommand:

    def test_root_exits_zero(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0

    def test_root_shows_ude_title(self):
        result = runner.invoke(app, [])
        assert "Unified Data Engine" in result.output or "ude" in result.output.lower()

    def test_root_shows_environment(self):
        result = runner.invoke(app, [])
        assert cfg.env in result.output


# ── ude --help ────────────────────────────────────────────────────────────────

class TestHelp:

    def test_help_exits_zero(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_lists_pipeline(self):
        result = runner.invoke(app, ["--help"])
        assert "pipeline" in result.output

    def test_help_lists_schema(self):
        result = runner.invoke(app, ["--help"])
        assert "schema" in result.output

    def test_help_lists_quarantine(self):
        result = runner.invoke(app, ["--help"])
        assert "quarantine" in result.output

    def test_help_lists_dbt(self):
        result = runner.invoke(app, ["--help"])
        assert "dbt" in result.output

    def test_help_lists_observe(self):
        result = runner.invoke(app, ["--help"])
        assert "observe" in result.output

    def test_pipeline_help(self):
        result = runner.invoke(app, ["pipeline", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_schema_help(self):
        result = runner.invoke(app, ["schema", "--help"])
        assert result.exit_code == 0

    def test_quarantine_help(self):
        result = runner.invoke(app, ["quarantine", "--help"])
        assert result.exit_code == 0

    def test_dbt_help(self):
        result = runner.invoke(app, ["dbt", "--help"])
        assert result.exit_code == 0

    def test_observe_help(self):
        result = runner.invoke(app, ["observe", "--help"])
        assert result.exit_code == 0


# ── Global flags ──────────────────────────────────────────────────────────────

class TestGlobalFlags:

    def test_custom_host_flag(self):
        result = runner.invoke(app, ["--host", "localhost", "status"])
        assert result.exit_code == 0

    def test_custom_port_flag(self):
        result = runner.invoke(app, ["--port", "8000", "status"])
        assert result.exit_code == 0

    def test_verbose_flag_accepted(self):
        result = runner.invoke(app, ["--verbose", "status"])
        assert result.exit_code == 0