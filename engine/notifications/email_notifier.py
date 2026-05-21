# engine/notifications/email_notifier.py
"""
Key expiry email notifications.

Runs as a daily background job — scans all api_key# records in Bigtable
and sends a warning email 14 days before expiry.

Requires Gmail SMTP config in ~/.ude/config.yml:
    smtp_email:    your-gmail@gmail.com
    smtp_app_password: xxxx-xxxx-xxxx-xxxx  (Gmail App Password)
"""

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

EXPIRY_WARNING_DAYS = 14
SMTP_HOST           = "smtp.gmail.com"
SMTP_PORT           = 587


def _load_smtp_config() -> tuple[Optional[str], Optional[str]]:
    """Load SMTP credentials from ~/.ude/config.yml."""
    cfg_file = Path.home() / ".ude" / "config.yml"
    if not cfg_file.exists():
        return None, None
    try:
        with cfg_file.open() as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("smtp_email"), cfg.get("smtp_app_password")
    except Exception:
        return None, None


def send_expiry_warning(
    to_email:     str,
    project_name: str,
    expires_at:   str,
    days_left:    int,
    smtp_email:   str,
    smtp_password: str,
) -> bool:
    """Send a key expiry warning email via Gmail SMTP. Returns True on success."""
    expires_date = expires_at[:10]

    subject = f"[UDE] Your API key expires in {days_left} days"

    html_body = f"""
<html>
<body style="font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 24px;">
  <div style="max-width: 600px; margin: 0 auto;">
    <h2 style="color: #58a6ff;">Unified Data Engine</h2>
    <p>Your API key for project <strong>{project_name}</strong> expires on
       <strong>{expires_date}</strong> ({days_left} days from now).</p>

    <p>After expiry, all API calls will return <code>401 Unauthorized</code>
       and your pipelines will stop ingesting data.</p>

    <h3 style="color: #f0883e;">Action required</h3>
    <p>Rotate your key before it expires:</p>
    <pre style="background: #161b22; padding: 12px; border-radius: 6px;">
ude auth rotate</pre>

    <p>Or via API:</p>
    <pre style="background: #161b22; padding: 12px; border-radius: 6px;">
curl -X POST https://your-engine/auth/key/rotate \\
  -H "Authorization: Bearer &lt;your-api-key&gt;"</pre>

    <p style="color: #8b949e; font-size: 12px; margin-top: 32px;">
      This is an automated message from the Unified Data Engine.
      To stop receiving these emails, revoke your key: <code>ude auth revoke</code>
    </p>
  </div>
</body>
</html>
"""

    text_body = (
        f"Your UDE API key for project '{project_name}' expires on {expires_date} "
        f"({days_left} days from now).\n\n"
        f"Rotate your key before it expires:\n\n"
        f"  ude auth rotate\n\n"
        f"After expiry, all API calls return 401 and pipelines stop ingesting data."
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_email
    msg["To"]      = to_email

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        logger.info(f"[Email] Expiry warning sent → {to_email} (expires {expires_date})")
        return True
    except Exception as exc:
        logger.error(f"[Email] Failed to send to {to_email}: {exc}")
        return False


def run_expiry_check() -> dict:
    """
    Scan all API keys and send expiry warnings for keys expiring within 14 days.
    Records notified_at to avoid duplicate emails.
    Called once per day from the engine cycle or as a standalone job.

    Returns: {"checked": N, "notified": N, "skipped": N, "errors": N}
    """
    smtp_email, smtp_password = _load_smtp_config()

    if not smtp_email or not smtp_password:
        logger.warning(
            "[Email] SMTP not configured — skipping expiry check. "
            "Run: ude auth email-config"
        )
        return {"checked": 0, "notified": 0, "skipped": 0, "errors": 0}

    from engine.state.bigtable_client import BigtableClient
    client   = BigtableClient()
    all_keys = client.all_keys()
    now      = datetime.now(timezone.utc)

    checked  = 0
    notified = 0
    skipped  = 0
    errors   = 0

    for key in all_keys:
        if not key.startswith("api_key#"):
            continue

        record = client.get(key)
        if not record or not isinstance(record, dict):
            continue

        if not record.get("active", True):
            continue

        expires_at = record.get("expires_at", "")
        if not expires_at:
            continue

        checked += 1

        try:
            expiry_dt = datetime.fromisoformat(expires_at)
            days_left = (expiry_dt - now).days

            # Only warn within the warning window
            if days_left > EXPIRY_WARNING_DAYS or days_left < 0:
                skipped += 1
                continue

            # Check if already notified in the last 24h
            notified_at = record.get("notified_at", "")
            if notified_at:
                notified_dt = datetime.fromisoformat(notified_at)
                if (now - notified_dt).total_seconds() < 86400:
                    skipped += 1
                    continue

            # Send warning
            to_email     = record.get("email", "")
            project_name = record.get("project_name", "unknown")

            if not to_email:
                skipped += 1
                continue

            success = send_expiry_warning(
                to_email=to_email,
                project_name=project_name,
                expires_at=expires_at,
                days_left=days_left,
                smtp_email=smtp_email,
                smtp_password=smtp_password,
            )

            if success:
                # Record notification time to avoid resending
                record["notified_at"] = now.isoformat()
                client.set(key, record)
                notified += 1
            else:
                errors += 1

        except Exception as exc:
            logger.error(f"[Email] Error processing key {key[:20]}: {exc}")
            errors += 1

    logger.info(
        f"[Email] Expiry check complete — "
        f"checked={checked} notified={notified} "
        f"skipped={skipped} errors={errors}"
    )

    return {
        "checked":  checked,
        "notified": notified,
        "skipped":  skipped,
        "errors":   errors,
    }