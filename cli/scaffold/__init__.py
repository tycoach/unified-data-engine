# cli/scaffold/__init__.py
"""
Scaffold layer — local file generation for ude init and ude pipeline new.

No live stack required. Pure Jinja2 template rendering + file I/O.
"""

from cli.scaffold.pipeline import scaffold_pipeline
from cli.scaffold.project  import scaffold_project

__all__ = ["scaffold_project", "scaffold_pipeline"]