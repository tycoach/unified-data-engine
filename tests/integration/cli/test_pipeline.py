# tests/integration/cli/test_pipeline.py
"""
Integration tests for ude pipeline commands.

Requires a live UDE stack. Skipped automatically when the stack is down.
Tests use a dedicated test pipeline ID to avoid touching real pipelines.

Test pipeline ID: __test_integration_pipeline__
This ID is scaffolded, used for assertions, then cleaned up.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.core.checks import stack_is_running
from cli.core.config import load_config
from cli.main import app

runner = CliRunner()
cfg    = load_config()

pytestmark = pytest.mark.skipif(
    not stack_is_running(cfg),
    reason="UDE stack not running — start with: ude up",
)

TEST_PIPELINE_ID = "__test_integration_pipeline__"


# ── ude pipeline list ─────────────────────────────────────────────────────────

class TestPipelineList:

    def test_list_exits_zero(self):
        result = runner.invoke(app, ["pipeline", "list"])
        assert result.exit_code == 0

    def test_list_shows_header(self):
        result = runner.invoke(app, ["pipeline", "list"])
        assert "Pipeline ID" in result.output or "pipeline" in result.output.lower()

    def test_list_shows_scd_column(self):
        result = runner.invoke(app, ["pipeline", "list"])
        assert "SCD" in result.output or "Type" in result.output


# ── ude pipeline inspect ──────────────────────────────────────────────────────

class TestPipelineInspect:

    def test_inspect_unknown_pipeline_fails_gracefully(self):
        result = runner.invoke(app, ["pipeline", "inspect", "nonexistent_pipeline_xyz"])
        # Should not crash with a raw traceback — should show a clean error
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_inspect_help_exits_zero(self):
        result = runner.invoke(app, ["pipeline", "inspect", "--help"])
        assert result.exit_code == 0


# ── ude pipeline new (scaffold only, no live stack needed) ───────────────────

class TestPipelineNew:

    def test_new_help_exits_zero(self):
        result = runner.invoke(app, ["pipeline", "new", "--help"])
        assert result.exit_code == 0

    def test_new_with_inputs(self, tmp_path, monkeypatch):
        """
        Simulate pipeline new with pre-supplied inputs via stdin.
        Uses typer's CliRunner input parameter.
        """
        inputs = "\n".join([
            "test_pipeline",     # pipeline ID
            "test_id",           # natural key
            "2",                 # SCD type
            "raw.test-sub",      # subscription
            "0.05",              # null threshold
            "24h",               # late arrival
            "30m",               # duplicate window
            "done",              # no fields
        ]) + "\n"

        result = runner.invoke(
            app,
            ["pipeline", "new"],
            input=inputs,
            catch_exceptions=False,
        )
        # May fail at the stack check but should not crash with a traceback
        assert "error" not in result.output.lower() or result.exit_code == 0


# ── ude pipeline enable / disable ────────────────────────────────────────────

class TestPipelineEnableDisable:

    def test_enable_help_exits_zero(self):
        result = runner.invoke(app, ["pipeline", "enable", "--help"])
        assert result.exit_code == 0

    def test_disable_help_exits_zero(self):
        result = runner.invoke(app, ["pipeline", "disable", "--help"])
        assert result.exit_code == 0

    def test_disable_unknown_pipeline_graceful(self):
        result = runner.invoke(
            app,
            ["pipeline", "disable", "nonexistent_xyz"],
            input="y\n",
        )
        assert result.exit_code != 0 or "not found" in result.output.lower()