# cli/scaffold/_renderer.py
"""
Shared Jinja2 rendering and file-write utilities for the scaffold layer.

"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from cli.core.errors import ScaffoldError

# Templates directory — adjacent to this file
TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_env() -> Environment:
    """Return a Jinja2 environment pointed at the templates directory."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,   # fail fast on missing variables
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_template(template_name: str, context: dict) -> str:
    """
    Render a Jinja2 template from cli/scaffold/templates/.
    """
    env = _get_env()
    try:
        template = env.get_template(template_name)
        return template.render(**context)
    except Exception as exc:
        raise ScaffoldError(
            f"Failed to render template '{template_name}': {exc}"
        ) from exc


def write_file(path: Path, content: str, overwrite: bool = True) -> None:
    """
    Write content to path, creating parent directories as needed.

    """
    if not overwrite and path.exists():
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ScaffoldError(f"Failed to write {path}: {exc}") from exc