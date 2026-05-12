"""
Shared Rich console instance for all ude CLI output.

"""

from rich.console import Console
from rich.theme import Theme

UDE_THEME = Theme({
    "success":    "bold green",
    "error":      "bold red",
    "warning":    "bold yellow",
    "info":       "bold cyan",
    "muted":      "dim",
    "pipeline":   "bold magenta",
    "batch":      "cyan",
    "schema":     "blue",
    "quarantine": "bold yellow",
    "dbt":        "bold green",
    "label":      "bold white",
})

console = Console(theme=UDE_THEME)
err_console = Console(stderr=True, theme=UDE_THEME)


def print_success(msg: str) -> None:
    console.print(f"[success]✓[/success] {msg}")


def print_error(msg: str) -> None:
    err_console.print(f"[error]✗[/error] {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[warning]![/warning] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[info]→[/info] {msg}")