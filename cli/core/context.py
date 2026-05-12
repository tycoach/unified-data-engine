"""
Typer context object — carries resolved config down to every command.

"""

from __future__ import annotations

from dataclasses import dataclass

from cli.core.config import UDEConfig


@dataclass
class UDEContext:
    config: UDEConfig
    verbose: bool = False
    output_json: bool = False  # --json flag: emit machine-readable output