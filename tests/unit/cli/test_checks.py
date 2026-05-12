# tests/unit/cli/test_checks.py
"""
Unit tests for cli/core/checks.py

Tests every pre-flight check in isolation:
  - assert_stack_running
  - assert_minisky_alive
  - assert_dbt_on_path
  - assert_project_exists
  - stack_is_running (silent version)
  - minisky_is_alive (silent version)

All HTTP calls and subprocess invocations are patched.
No network or filesystem access in these tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cli.core.checks import (
    assert_dbt_on_path,
    assert_minisky_alive,
    assert_project_exists,
    assert_stack_running,
    minisky_is_alive,
    stack_is_running,
)
from cli.core.config import UDEConfig
from cli.core.errors import (
    DbtNotFoundError,
    MiniskyNotRunningError,
    NoProjectError,
    StackNotRunningError,
)


def _local_cfg(**kwargs) -> UDEConfig:
    return UDEConfig(
        host="localhost",
        port=8000,
        env="local",
        minisky_url="http://localhost:9099",
        **kwargs,
    )


def _prod_cfg() -> UDEConfig:
    return UDEConfig(host="prod.internal", port=8000, env="production")


# ── assert_stack_running ──────────────────────────────────────────────────────

class TestAssertStackRunning:

    def test_passes_when_api_responds_200(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("cli.core.checks.httpx.get", return_value=mock_resp):
            assert_stack_running(_local_cfg())

    def test_raises_on_connect_error(self):
        with patch("cli.core.checks.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(StackNotRunningError) as exc_info:
                assert_stack_running(_local_cfg())
        assert "localhost" in str(exc_info.value)
        assert "8000" in str(exc_info.value)

    def test_raises_on_timeout(self):
        with patch("cli.core.checks.httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(StackNotRunningError):
                assert_stack_running(_local_cfg())

    def test_raises_on_http_status_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        with patch("cli.core.checks.httpx.get", return_value=mock_resp):
            with pytest.raises(StackNotRunningError):
                assert_stack_running(_local_cfg())

    def test_error_message_contains_hint(self):
        with patch("cli.core.checks.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(StackNotRunningError) as exc_info:
                assert_stack_running(_local_cfg())
        assert "ude up" in str(exc_info.value)


# ── assert_minisky_alive ──────────────────────────────────────────────────────

class TestAssertMiniskyAlive:

    def test_passes_when_minisky_responds(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("cli.core.checks.httpx.get", return_value=mock_resp):
            assert_minisky_alive(_local_cfg())

    def test_raises_on_connect_error(self):
        with patch("cli.core.checks.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(MiniskyNotRunningError) as exc_info:
                assert_minisky_alive(_local_cfg())
        assert "minisky start" in str(exc_info.value)

    def test_raises_on_timeout(self):
        with patch("cli.core.checks.httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(MiniskyNotRunningError):
                assert_minisky_alive(_local_cfg())

    def test_skips_check_in_production(self):
        assert_minisky_alive(_prod_cfg())

    def test_skips_check_in_staging(self):
        cfg = UDEConfig(host="staging.internal", port=8000, env="staging")
        assert_minisky_alive(cfg)


# ── assert_dbt_on_path ────────────────────────────────────────────────────────

class TestAssertDbtOnPath:

    def test_passes_when_dbt_found_and_runs(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("cli.core.checks.shutil.which", return_value="/usr/bin/dbt"):
            with patch("cli.core.checks.subprocess.run", return_value=mock_result):
                assert_dbt_on_path()

    def test_raises_when_dbt_not_on_path(self):
        with patch("cli.core.checks.shutil.which", return_value=None):
            with pytest.raises(DbtNotFoundError) as exc_info:
                assert_dbt_on_path()
        assert "pip install" in str(exc_info.value)

    def test_raises_when_dbt_version_fails(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("cli.core.checks.shutil.which", return_value="/usr/bin/dbt"):
            with patch("cli.core.checks.subprocess.run", return_value=mock_result):
                with pytest.raises(DbtNotFoundError):
                    assert_dbt_on_path()

    def test_raises_when_subprocess_times_out(self):
        with patch("cli.core.checks.shutil.which", return_value="/usr/bin/dbt"):
            with patch(
                "cli.core.checks.subprocess.run",
                side_effect=subprocess.TimeoutExpired("dbt", 10),
            ):
                with pytest.raises(DbtNotFoundError):
                    assert_dbt_on_path()

    def test_error_message_contains_install_hint(self):
        with patch("cli.core.checks.shutil.which", return_value=None):
            with pytest.raises(DbtNotFoundError) as exc_info:
                assert_dbt_on_path()
        assert "dbt-bigquery" in str(exc_info.value)


# ── assert_project_exists ─────────────────────────────────────────────────────

class TestAssertProjectExists:

    def test_passes_when_engine_yml_exists(self):
        """
        PosixPath.exists is a read-only C slot in Python 3.12 — patch.object
        on a Path instance fails with AttributeError. The correct approach is
        to patch Path itself inside cli.core.checks so every call to Path()
        returns a MagicMock whose .exists() we control completely.
        """
        hit  = MagicMock(**{"exists.return_value": True})
        miss = MagicMock(**{"exists.return_value": False})

        # assert_project_exists instantiates exactly 3 Path objects.
        # any() short-circuits on the first True.
        with patch("cli.core.checks.Path", side_effect=[hit, miss, miss]):
            assert_project_exists()  # should not raise

    def test_passes_when_dbt_project_yml_exists(self):
        """Any one of the three markers is sufficient."""
        miss = MagicMock(**{"exists.return_value": False})
        hit  = MagicMock(**{"exists.return_value": True})

        with patch("cli.core.checks.Path", side_effect=[miss, miss, hit]):
            assert_project_exists()  # should not raise

    def test_raises_when_no_project_markers_found(self):
        marker = MagicMock(**{"exists.return_value": False})
        with patch("cli.core.checks.Path", return_value=marker):
            with pytest.raises(NoProjectError) as exc_info:
                assert_project_exists()
        assert "ude init" in str(exc_info.value)


# ── Silent versions ───────────────────────────────────────────────────────────

class TestSilentChecks:

    def test_stack_is_running_returns_true(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("cli.core.checks.httpx.get", return_value=mock_resp):
            assert stack_is_running(_local_cfg()) is True

    def test_stack_is_running_returns_false(self):
        with patch("cli.core.checks.httpx.get", side_effect=httpx.ConnectError("refused")):
            assert stack_is_running(_local_cfg()) is False

    def test_minisky_is_alive_returns_true(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("cli.core.checks.httpx.get", return_value=mock_resp):
            assert minisky_is_alive(_local_cfg()) is True

    def test_minisky_is_alive_returns_false(self):
        with patch("cli.core.checks.httpx.get", side_effect=httpx.ConnectError("refused")):
            assert minisky_is_alive(_local_cfg()) is False

    def test_minisky_is_alive_true_in_production(self):
        """Silent check always returns True in non-local envs (check is skipped)."""
        assert minisky_is_alive(_prod_cfg()) is True