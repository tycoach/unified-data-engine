# tests/integration/cli/test_quarantine.py
"""
Integration tests for ude quarantine commands.

Requires a live UDE stack. Skipped automatically when the stack is down.

Note: These tests are read-only where possible (list, inspect).
Approve/reject/replay are tested only against synthetic quarantine
entries created by the test seed data — never real production batches.
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


# ── ude quarantine list ───────────────────────────────────────────────────────

class TestQuarantineList:

    def test_list_exits_zero(self):
        result = runner.invoke(app, ["quarantine", "list"])
        assert result.exit_code == 0

    def test_list_shows_batch_id_column(self):
        result = runner.invoke(app, ["quarantine", "list"])
        assert "Batch ID" in result.output or "batch" in result.output.lower()

    def test_list_pipeline_filter(self):
        result = runner.invoke(app, ["quarantine", "list", "--pipeline", "customers"])
        assert result.exit_code == 0

    def test_list_reason_filter(self):
        result = runner.invoke(app, ["quarantine", "list", "--reason", "SCHEMA_BROKEN"])
        assert result.exit_code == 0

    def test_list_limit_flag(self):
        result = runner.invoke(app, ["quarantine", "list", "--limit", "5"])
        assert result.exit_code == 0


# ── ude quarantine inspect ────────────────────────────────────────────────────

class TestQuarantineInspect:

    def test_inspect_unknown_batch_graceful(self):
        result = runner.invoke(app, ["quarantine", "inspect", "nonexistent-batch-id-xyz"])
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_inspect_help_exits_zero(self):
        result = runner.invoke(app, ["quarantine", "inspect", "--help"])
        assert result.exit_code == 0


# ── ude quarantine approve / reject / replay ──────────────────────────────────

class TestQuarantineActions:

    def test_approve_help_exits_zero(self):
        result = runner.invoke(app, ["quarantine", "approve", "--help"])
        assert result.exit_code == 0

    def test_reject_help_exits_zero(self):
        result = runner.invoke(app, ["quarantine", "reject", "--help"])
        assert result.exit_code == 0

    def test_replay_help_exits_zero(self):
        result = runner.invoke(app, ["quarantine", "replay", "--help"])
        assert result.exit_code == 0

    def test_approve_unknown_batch_graceful(self):
        result = runner.invoke(
            app,
            ["quarantine", "approve", "nonexistent-batch-xyz"],
            input="test reason\nn\n",  # reason + decline confirmation
        )
        # Either declined by user (exit 0) or API 404 handled cleanly
        assert "Traceback" not in result.output

    def test_reject_unknown_batch_graceful(self):
        result = runner.invoke(
            app,
            ["quarantine", "reject", "nonexistent-batch-xyz"],
            input="test reason\nn\n",  # reason + decline confirmation
        )
        assert "Traceback" not in result.output

    def test_replay_unknown_batch_graceful(self):
        result = runner.invoke(
            app,
            ["quarantine", "replay", "nonexistent-batch-xyz"],
        )
        # Should show not_approved or not found — not a raw crash
        assert "Traceback" not in result.output