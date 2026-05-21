# cli/commands/auth.py
"""
ude auth — API key management.

Commands:
    ude auth signup        — self-service signup
    ude auth whoami        — show identity + expiry warning
    ude auth rotate        — rotate API key
    ude auth revoke        — revoke API key permanently
    ude auth list-keys     — list all accounts (engine owner only)
    ude auth audit         — view audit log (--watch for live stream)
    ude auth email-config  — configure Gmail SMTP for expiry notifications
    ude auth webhook-config — configure webhook URL for suspicious activity alerts
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer

from cli.core.context import UDEContext
from cli.output.console import console, print_error, print_info, print_success, print_warning

app = typer.Typer(help="Authentication — signup, whoami, rotate, revoke, list-keys, audit")


def _ctx(ctx: typer.Context) -> UDEContext:
    return ctx.obj


# ── ude auth signup ───────────────────────────────────────────────────────────

@app.command(name="signup")
def signup(
    ctx: typer.Context,
    email: Optional[str] = typer.Option(None, "--email", "-e"),
    project_name: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Create an account and get an API key (saved to ~/.ude/config.yml)."""
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
    expires_at    = result.get("expires_at", "")[:10]

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
        f"[bold]Project token:[/bold] [muted]{project_token}[/muted]\n"
        f"[bold]Expires:[/bold]       [muted]{expires_at}[/muted]\n\n"
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
    """Show current identity, project, and key expiry."""
    from cli.client.auth import AuthClient
    from rich.table import Table
    from rich.panel import Panel

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

    days_left  = result.get("days_until_expiry")
    expires_at = result.get("expires_at", "")[:10]

    if days_left is not None:
        if days_left < 0:
            expiry_str = f"[error]EXPIRED {abs(days_left)} days ago[/error]"
        elif days_left <= 14:
            expiry_str = f"[warning]{expires_at} ({days_left} days left — rotate soon)[/warning]"
        else:
            expiry_str = f"[success]{expires_at}[/success] [muted]({days_left} days left)[/muted]"
    else:
        expiry_str = expires_at or "—"

    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", min_width=18)
    table.add_column()
    table.add_row("Email",         result.get("email", "—"))
    table.add_row("Project",       result.get("project_name", "—"))
    table.add_row("Project token", result.get("project_token", "—"))
    table.add_row("API key",       result.get("api_key", "—"))
    table.add_row("Expires",       expiry_str)
    table.add_row("Last used",     result.get("last_used_at", "—")[:19] if result.get("last_used_at") else "—")

    console.print()
    console.print(Panel(table, title="[bold]Current Identity[/bold]", border_style="cyan", padding=(1, 2)))

    if days_left is not None and 0 <= days_left <= 14:
        console.print()
        print_warning(f"Your API key expires in {days_left} days.")
        print_info("Rotate now: [bold]ude auth rotate[/bold]")

    if days_left is not None and days_left < 0:
        console.print()
        print_error("Your API key has expired. All API calls are failing.")
        print_info("Get a new key: [bold]ude auth signup[/bold]")

    console.print()


# ── ude auth rotate ───────────────────────────────────────────────────────────

@app.command(name="rotate")
def rotate(ctx: typer.Context) -> None:
    """Rotate your API key — old key invalidated, TTL reset to 90 days."""
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

    new_key    = result.get("api_key", "")
    expires_at = result.get("expires_at", "")[:10]

    cfg = _load_file() if config_exists() else {}
    cfg["api_key"] = new_key
    write_config(cfg)

    console.print()
    print_success("API key rotated.")
    console.print(f"  [bold]New key:[/bold]  [info]{new_key}[/info]")
    console.print(f"  [bold]Expires:[/bold]   [muted]{expires_at}[/muted]")
    console.print(f"  [muted]Saved to ~/.ude/config.yml[/muted]")
    console.print()


# ── ude auth revoke ───────────────────────────────────────────────────────────

@app.command(name="revoke")
def revoke(ctx: typer.Context) -> None:
    """Revoke your API key permanently."""
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

    cfg = _load_file() if config_exists() else {}
    cfg.pop("api_key", None)
    write_config(cfg)

    print_success("API key revoked.")
    print_info("Run: ude auth signup to create a new account.")
    console.print()


# ── ude auth list-keys ────────────────────────────────────────────────────────

@app.command(name="list-keys")
def list_keys(ctx: typer.Context) -> None:
    """List all registered accounts (engine owner only)."""
    from cli.client.auth import AuthClient
    from rich.table import Table
    from rich.panel import Panel

    ude_ctx = _ctx(ctx)

    if not ude_ctx.config.api_key:
        print_warning("No API key configured.")
        raise typer.Exit()

    if ude_ctx.config.project_token != "__engine__":
        print_error("list-keys is restricted to the engine owner.")
        print_info("Set project_token: __engine__ in ~/.ude/config.yml")
        raise typer.Exit(code=1)

    try:
        client = AuthClient(ude_ctx.config)
        result = client.list_keys()
    except Exception as exc:
        print_error(f"Failed to list keys: {exc}")
        raise typer.Exit(code=1)

    keys = result.get("keys", [])
    if not keys:
        print_info("No registered accounts.")
        raise typer.Exit()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Email",     min_width=28)
    table.add_column("Project",   min_width=20)
    table.add_column("Status",    justify="center")
    table.add_column("Expires",   min_width=12)
    table.add_column("Days left", justify="right")
    table.add_column("Last used", style="muted")

    for k in keys:
        days_left = k.get("days_left")
        active    = k.get("active", True)
        expires   = k.get("expires_at", "")[:10]

        if not active:
            status = "[error]revoked[/error]"
        elif days_left is not None and days_left < 0:
            status = "[error]expired[/error]"
        elif days_left is not None and days_left <= 14:
            status = "[warning]expiring[/warning]"
        else:
            status = "[success]active[/success]"

        days_str  = f"[warning]{days_left}[/warning]" if days_left is not None and days_left <= 14 else (str(days_left) if days_left is not None else "—")
        last_used = (k.get("last_used_at") or "")[:10] or "never"

        table.add_row(k.get("email", "—"), k.get("project_name", "—"), status, expires, days_str, last_used)

    console.print()
    console.print(Panel(table, title=f"[bold]Registered Accounts[/bold] ({len(keys)} total)", border_style="cyan", padding=(1, 2)))
    console.print()


# ── ude auth audit ────────────────────────────────────────────────────────────

@app.command(name="audit")
def audit(
    ctx: typer.Context,
    limit:  int            = typer.Option(20,    "--limit",  "-n", help="Number of entries"),
    email:  Optional[str]  = typer.Option(None,  "--email",  "-e", help="Filter by email"),
    method: Optional[str]  = typer.Option(None,  "--method", "-m", help="Filter by HTTP method (GET, POST...)"),
    status: Optional[int]  = typer.Option(None,  "--status", "-s", help="Filter by status code"),
    watch:  bool           = typer.Option(False, "--watch",  "-w", help="Live stream — poll every 5s"),
) -> None:
    """
    View recent API audit log entries.

    Engine owner sees all entries. Regular users see only their own.
    Use --watch for a live stream that updates every 5 seconds.
    """
    from cli.client.auth import AuthClient
    from rich.table import Table
    from rich.panel import Panel
    from rich.live import Live

    ude_ctx = _ctx(ctx)

    if not ude_ctx.config.api_key:
        print_warning("No API key configured.")
        print_info("Run: ude auth signup")
        raise typer.Exit()

    client = AuthClient(ude_ctx.config)

    def _fetch_entries():
        try:
            result = client.audit_log(limit=limit, email=email)
            entries = result.get("entries", [])
            # Apply local filters
            if method:
                entries = [e for e in entries if e.get("method", "").upper() == method.upper()]
            if status:
                entries = [e for e in entries if e.get("status_code") == status]
            return entries
        except Exception as exc:
            print_error(f"Failed to fetch audit log: {exc}")
            return []

    def _build_table(entries) -> Panel:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("Timestamp",  min_width=19, style="muted")
        table.add_column("Email",      min_width=24)
        table.add_column("Method",     justify="center", min_width=8)
        table.add_column("Path",       min_width=28)
        table.add_column("Status",     justify="center", min_width=6)
        table.add_column("ms",         justify="right",  min_width=6)

        for e in entries:
            s = e.get("status_code", 0)
            status_str = (
                f"[success]{s}[/success]" if s < 300
                else f"[warning]{s}[/warning]" if s < 500
                else f"[error]{s}[/error]"
            )
            table.add_row(
                e.get("timestamp", "")[:19],
                e.get("email", "—"),
                e.get("method", "—"),
                e.get("path", "—"),
                status_str,
                str(e.get("duration_ms", "—")),
            )

        subtitle = "[muted]Ctrl+C to stop[/muted]" if watch else ""
        return Panel(
            table,
            title=f"[bold]Audit Log[/bold] ({len(entries)} entries)",
            subtitle=subtitle,
            border_style="cyan",
            padding=(1, 2),
        )

    if not watch:
        entries = _fetch_entries()
        if not entries:
            print_info("No audit log entries found.")
            raise typer.Exit()
        console.print()
        console.print(_build_table(entries))
        console.print()
        return

    # Live watch mode
    console.print()
    print_info("Streaming audit log — polling every 5s. Ctrl+C to stop.")
    console.print()

    try:
        with Live(console=console, refresh_per_second=0.5) as live:
            while True:
                entries = _fetch_entries()
                live.update(_build_table(entries))
                time.sleep(5)
    except KeyboardInterrupt:
        console.print()
        print_info("Stopped.")
        console.print()


# ── ude auth email-config ─────────────────────────────────────────────────────

@app.command(name="email-config")
def email_config(
    ctx: typer.Context,
    smtp_email:    Optional[str] = typer.Option(None, "--email",    "-e", help="Gmail address"),
    smtp_password: Optional[str] = typer.Option(None, "--password", "-p", help="Gmail App Password"),
    test:          bool          = typer.Option(False, "--test",         help="Send a test email after saving"),
) -> None:
    """
    Configure Gmail SMTP for API key expiry notifications.

    Requires a Gmail App Password (not your regular Gmail password).
    Generate one at: Google Account → Security → App passwords
    """
    from cli.core.config import write_config, _load_file, config_exists
    from rich.panel import Panel

    console.print()
    console.print("[bold]UDE — Email Notification Config[/bold]")
    console.print("[muted]Configure Gmail SMTP for key expiry warnings.[/muted]")
    console.print()
    console.print("  [muted]Generate an App Password at:[/muted]")
    console.print("  [info]Google Account → Security → 2-Step Verification → App passwords[/info]")
    console.print()

    smtp_email    = smtp_email    or typer.prompt("Gmail address")
    smtp_password = smtp_password or typer.prompt("Gmail App Password", hide_input=True)

    cfg = _load_file() if config_exists() else {}
    cfg["smtp_email"]        = smtp_email
    cfg["smtp_app_password"] = smtp_password
    write_config(cfg)

    print_success("SMTP config saved to ~/.ude/config.yml")

    if test:
        print_info(f"Sending test email to {smtp_email}...")
        try:
            from engine.notifications.email_notifier import send_expiry_warning
            ok = send_expiry_warning(
                to_email=smtp_email,
                project_name="test-project",
                expires_at="2026-06-04T00:00:00+00:00",
                days_left=14,
                smtp_email=smtp_email,
                smtp_password=smtp_password,
            )
            if ok:
                print_success("Test email sent successfully.")
            else:
                print_error("Test email failed — check credentials.")
        except Exception as exc:
            print_error(f"Test email failed: {exc}")

    console.print()
    console.print(Panel(
        f"[bold]SMTP email:[/bold]    [info]{smtp_email}[/info]\n"
        f"[bold]App password:[/bold]  [muted]{'*' * len(smtp_password)}[/muted]\n\n"
        f"[muted]Keys expiring within 14 days will receive a warning email.\n"
        f"Notifications run once per day automatically.[/muted]",
        title="[bold]Email Config[/bold]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


# ── ude auth webhook-config ───────────────────────────────────────────────────

@app.command(name="webhook-config")
def webhook_config(
    ctx: typer.Context,
    url:  Optional[str] = typer.Option(None,  "--url",  "-u", help="Webhook URL"),
    test: bool          = typer.Option(False, "--test",        help="Fire a test webhook after saving"),
) -> None:
    """
    Configure a webhook URL for suspicious activity alerts.

    Compatible with Slack, Discord, and any HTTP endpoint.
    Fires when the same API key is used from 2 different IPs within 60 seconds.
    """
    from cli.core.config import write_config, _load_file, config_exists
    from rich.panel import Panel

    console.print()
    console.print("[bold]UDE — Webhook Config[/bold]")
    console.print("[muted]Get alerts when suspicious activity is detected.[/muted]")
    console.print()
    console.print("  [muted]Compatible with: Slack, Discord, or any HTTP POST endpoint.[/muted]")
    console.print()

    url = url or typer.prompt("Webhook URL")

    cfg = _load_file() if config_exists() else {}
    cfg["webhook_url"] = url
    write_config(cfg)

    print_success("Webhook URL saved to ~/.ude/config.yml")

    if test:
        print_info("Firing test webhook...")
        try:
            from engine.notifications.webhook import fire_webhook
            ok = fire_webhook(
                webhook_url=url,
                suspicious={
                    "api_key_truncated": "ude_live_test...",
                    "ip_original":       "203.0.113.1",
                    "ip_new":            "198.51.100.42",
                    "window_seconds":    60,
                    "triggered_at":      "2026-05-21T12:00:00+00:00",
                },
                email="test@example.com",
                project_name="test-project",
            )
            if ok:
                print_success("Test webhook fired successfully.")
            else:
                print_error("Webhook failed — check the URL.")
        except Exception as exc:
            print_error(f"Test webhook failed: {exc}")

    console.print()
    console.print(Panel(
        f"[bold]Webhook URL:[/bold] [info]{url}[/info]\n\n"
        f"[muted]You will receive an alert when:\n"
        f"  • The same API key is used from 2 different IPs within 60s\n\n"
        f"Test with: [bold]ude auth webhook-config --test[/bold][/muted]",
        title="[bold]Webhook Config[/bold]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()