# tests/unit/cli/test_config.py
"""
Unit tests for cli/core/config.py

All file and env interaction is patched — no real disk or env reads.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from cli.core.config import (
    DEFAULT_ENV,
    DEFAULT_HOST,
    DEFAULT_PORT,
    UDEConfig,
    load_config,
    write_config,
)


# ── Defaults ──────────────────────────────────────────────────────────────────

class TestDefaults:

    def test_default_host(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config()
        assert cfg.host == DEFAULT_HOST

    def test_default_port(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config()
        assert cfg.port == DEFAULT_PORT

    def test_default_env(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config()
        assert cfg.env == DEFAULT_ENV

    def test_default_is_local(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config()
        assert cfg.is_local is True

    def test_api_base_url_format(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config()
        assert cfg.api_base_url == f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


# ── Explicit args override everything ─────────────────────────────────────────

class TestExplicitArgs:

    def test_explicit_host_overrides_default(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config(host="myhost.internal")
        assert cfg.host == "myhost.internal"

    def test_explicit_port_overrides_default(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config(port=9999)
        assert cfg.port == 9999

    def test_explicit_args_override_env_vars(self):
        with patch.dict(os.environ, {"UDE_HOST": "env-host", "UDE_PORT": "7777"}):
            with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
                mock_cfg.exists.return_value = False
                cfg = load_config(host="explicit-host", port=8888)
        assert cfg.host == "explicit-host"
        assert cfg.port == 8888


# ── Environment variables ─────────────────────────────────────────────────────

class TestEnvVars:

    def test_ude_host_env_var(self):
        with patch.dict(os.environ, {"UDE_HOST": "env-host.internal"}):
            with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
                mock_cfg.exists.return_value = False
                cfg = load_config()
        assert cfg.host == "env-host.internal"

    def test_ude_port_env_var(self):
        with patch.dict(os.environ, {"UDE_PORT": "9001"}):
            with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
                mock_cfg.exists.return_value = False
                cfg = load_config()
        assert cfg.port == 9001

    def test_ude_env_env_var(self):
        with patch.dict(os.environ, {"UDE_ENV": "production"}):
            with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
                mock_cfg.exists.return_value = False
                cfg = load_config()
        assert cfg.env == "production"

    def test_production_env_is_not_local(self):
        with patch.dict(os.environ, {"UDE_ENV": "production"}):
            with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
                mock_cfg.exists.return_value = False
                cfg = load_config()
        assert cfg.is_local is False

    def test_minisky_url_env_var(self):
        with patch.dict(os.environ, {"MINISKY_URL": "http://minisky.test:9099"}):
            with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
                mock_cfg.exists.return_value = False
                cfg = load_config()
        assert cfg.minisky_url == "http://minisky.test:9099"


# ── Config file ───────────────────────────────────────────────────────────────

class TestConfigFile:

    def _patch_config_file(self, content: str):
        """Helper: patch CONFIG_FILE.exists() = True and return content."""
        import yaml
        parsed = yaml.safe_load(content)

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.open.return_value.__enter__ = lambda s: s
        mock_path.open.return_value.__exit__ = MagicMock(return_value=False)
        mock_path.open.return_value.read.return_value = content

        return mock_path, parsed

    def test_file_host_used_when_no_env_var(self):
        yaml_content = "host: file-host\nport: 8000\nenv: local\n"
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = True
            with patch("cli.core.config._load_file", return_value={"host": "file-host"}):
                cfg = load_config()
        assert cfg.host == "file-host"

    def test_env_var_overrides_file(self):
        with patch.dict(os.environ, {"UDE_HOST": "env-wins"}):
            with patch("cli.core.config._load_file", return_value={"host": "file-loses"}):
                cfg = load_config()
        assert cfg.host == "env-wins"

    def test_missing_config_file_returns_defaults(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = False
            cfg = load_config()
        assert cfg.host == DEFAULT_HOST
        assert cfg.port == DEFAULT_PORT

    def test_malformed_config_file_returns_defaults(self):
        with patch("cli.core.config.CONFIG_FILE") as mock_cfg:
            mock_cfg.exists.return_value = True
            with patch("cli.core.config._load_file", return_value={}):
                cfg = load_config()
        assert cfg.host == DEFAULT_HOST


# ── UDEConfig properties ──────────────────────────────────────────────────────

class TestUDEConfigProperties:

    def test_api_base_url(self):
        cfg = UDEConfig(host="myhost", port=9000)
        assert cfg.api_base_url == "http://myhost:9000"

    def test_is_local_true(self):
        cfg = UDEConfig(env="local")
        assert cfg.is_local is True

    def test_is_local_false_staging(self):
        cfg = UDEConfig(env="staging")
        assert cfg.is_local is False

    def test_is_local_false_production(self):
        cfg = UDEConfig(env="production")
        assert cfg.is_local is False