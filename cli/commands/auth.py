# cli/commands/auth.py
"""
ude auth — API key management.

Commands:
    ude auth signup    — self-service signup, saves key to ~/.ude/config.yml
    ude auth whoami    — show current identity + project
    ude auth rotate    — rotate API key (old key invalidated)
    ude auth revoke    — revoke API key permanently
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Authentication — signup, whoami, rotate, revoke")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude auth signup ───────────────────────────────────────────────────────────

@app.command(name="signup")
def signup(
    ctx: typer.Context,
    email: Optional[str] = typer.Option(
        None, "--email", "-e",
        help="Your email address",
    ),
    project_name: Optional[str] = typer.Option(
        None, "--project", "-p",
        help="Your project name (e.g. acme-analytics)",
    ),
) -> None:
    """
    Create an account and get an API key.

    The API key is saved to ~/.ude/config.yml automatically.
    It is only shown once — store it securely.
    """
    from cli.client.auth import AuthClient
    from cli.core.config import write_config, _load_file, config_exists
    from rich.panel import Panel

    ude_ctx = _ctx(ctx)

    console.print()
    console.print("[bold]UDE — Create Account[/bold]")
    console.print("[muted]Get an API key to connect to the UDE engine.[/muted]")
    console.print()

    email        = email        or typer.prompt("Email address")
    project_name = project_name or typer.prompt("Project name", default=Path.cwd().name)

    print_info(f"Creating account for {email}...")

    try:
        client = AuthClient(ude_ctx.config)
        result = client.signup(email=email, project_name=project_name)
    except Exception as exc:
        print_error(f"Signup failed: {exc}")
        raise typer.Exit(code=1)

    api_key       = result.get("api_key", "")
    project_token = result.get("project_token", "")

    # Save to ~/.ude/config.yml
    cfg = _load_file() if config_exists() else {}
    cfg.update({
        "host":          cfg.get("host", "localhost"),
        "port":          cfg.get("port", 8000),
        "env":           cfg.get("env", "local"),
        "minisky_url":   cfg.get("minisky_url", "http://localhost:8080"),
        "timeout":       cfg.get("timeout", 30),
        "api_key":       api_key,
        "project_token": project_token,
        "project_name":  project_name,
        "email":         email,
    })
    write_config(cfg)

    console.print()
    console.print(Panel(
        f"[bold]API Key:[/bold] [info]{api_key}[/info]\n\n"
        f"[bold]Project token:[/bold] [muted]{project_token}[/muted]\n\n"
        f"[muted]Saved to ~/.ude/config.yml\n"
        f"This key will not be shown again — store it securely.[/muted]",
        title="[success]✓ Account created[/success]",
        border_style="green",
        padding=(1, 2),
    ))
    console.print()
    print_info("Next step: [bold]ude pipeline new[/bold] to register your first pipeline.")
    console.print()


# ── ude auth whoami ───────────────────────────────────────────────────────────

@app.command(name="whoami")
def whoami(ctx: typer.Context) -> None:
    """Show the identity associated with your current API key."""
    from cli.client.auth import AuthClient
    from rich.table import Table

    ude_ctx = _ctx(ctx)

    if not ude_ctx.config.api_key:
        print_warning("No API key configured.")
        print_info("Run: ude auth signup")
        raise typer.Exit()

    try:
        client = AuthClient(ude_ctx.config)
        result = client.whoami()
    except Exception as exc:
        print_error(f"Could not fetch identity: {exc}")
        raise typer.Exit(code=1)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", min_width=16)
    table.add_column(style="bold")

    table.add_row("Email",         result.get("email", "—"))
    table.add_row("Project",       result.get("project_name", "—"))
    table.add_row("Project token", result.get("project_token", "—"))
    table.add_row("API key",       result.get("api_key", "—"))

    from rich.panel import Panel
    console.print()
    console.print(Panel(
        table,
        title="[bold]Current Identity[/bold]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


# ── ude auth rotate ───────────────────────────────────────────────────────────

@app.command(name="rotate")
def rotate(ctx: typer.Context) -> None:
    """
    Rotate your API key.

    The old key is immediately invalidated.
    ~/.ude/config.yml is updated with the new key automatically.
    """
    from cli.client.auth import AuthClient
    from cli.core.config import write_config, _load_file, config_exists

    ude_ctx = _ctx(ctx)

    if not ude_ctx.config.api_key:
        print_warning("No API key configured.")
        print_info("Run: ude auth signup")
        raise typer.Exit()

    confirm = typer.confirm(
        "Rotate your API key? The current key will be immediately invalidated.",
        default=False,
    )
    if not confirm:
        print_info("Aborted.")
        raise typer.Exit()

    try:
        client = AuthClient(ude_ctx.config)
        result = client.rotate()
    except Exception as exc:
        print_error(f"Key rotation failed: {exc}")
        raise typer.Exit(code=1)

    new_key = result.get("api_key", "")

    # Update ~/.ude/config.yml
    cfg = _load_file() if config_exists() else {}
    cfg["api_key"] = new_key
    write_config(cfg)

    console.print()
    print_success("API key rotated.")
    console.print(f"  [bold]New key:[/bold] [info]{new_key}[/info]")
    console.print(f"  [muted]Saved to ~/.ude/config.yml[/muted]")
    console.print()


# ── ude auth revoke ───────────────────────────────────────────────────────────

@app.command(name="revoke")
def revoke(ctx: typer.Context) -> None:
    """
    Revoke your API key permanently.

    All subsequent requests with this key will return 401.
    Run ude auth signup to create a new account.
    """
    from cli.client.auth import AuthClient
    from cli.core.config import write_config, _load_file, config_exists

    ude_ctx = _ctx(ctx)

    if not ude_ctx.config.api_key:
        print_warning("No API key configured.")
        raise typer.Exit()

    console.print()
    print_warning("This will permanently revoke your API key.")
    console.print("  You will need to sign up again to get a new key.")
    console.print()

    confirm = typer.confirm("Are you sure?", default=False)
    if not confirm:
        print_info("Aborted.")
        raise typer.Exit()

    try:
        client = AuthClient(ude_ctx.config)
        client.revoke()
    except Exception as exc:
        print_error(f"Revocation failed: {exc}")
        raise typer.Exit(code=1)

    # Remove key from config
    cfg = _load_file() if config_exists() else {}
    cfg.pop("api_key", None)
    write_config(cfg)

    print_success("API key revoked.")
    print_info("Run: ude auth signup to create a new account.")
    console.print()