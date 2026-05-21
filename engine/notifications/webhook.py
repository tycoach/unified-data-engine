# engine/notifications/webhook.py
"""
Suspicious activity detection + webhook notifications.

Detects: same API key used from 2 different IPs within 60 seconds.
Posts a JSON payload to the configured webhook URL.

Config in ~/.ude/config.yml:
    webhook_url: https://hooks.slack.com/services/...
                 https://server.com/ude-alerts
                 https://discord.com/api/webhooks/...
"""

import json
import logging
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory store: api_key → [(ip, timestamp), ...]
# Cleared on server restart — intentional (short-window detection only)
_ip_activity: dict[str, list[tuple[str, float]]] = defaultdict(list)

DETECTION_WINDOW_SECONDS = 60


def record_request(api_key: str, ip: str) -> Optional[dict]:
    """
    Record an API request and check for suspicious activity.

    Returns a suspicious activity dict if detected, None otherwise.
    Called from the auth middleware on every authenticated request.
    """
    now    = time.time()
    cutoff = now - DETECTION_WINDOW_SECONDS
    key    = api_key[:16]  # truncate for memory efficiency

    # Drop old entries outside the window
    _ip_activity[key] = [
        (stored_ip, ts)
        for stored_ip, ts in _ip_activity[key]
        if ts > cutoff
    ]

    # Check if a different IP was seen in the window
    seen_ips = {stored_ip for stored_ip, _ in _ip_activity[key]}

    suspicious = None
    if seen_ips and ip not in seen_ips:
        # New IP appeared within the detection window
        first_ip  = next(iter(seen_ips))
        suspicious = {
            "api_key_truncated": api_key[:12] + "...",
            "ip_original":       first_ip,
            "ip_new":            ip,
            "window_seconds":    DETECTION_WINDOW_SECONDS,
            "triggered_at":      datetime.now(timezone.utc).isoformat(),
        }
        logger.warning(
            f"[Webhook] Suspicious activity detected: "
            f"key={api_key[:12]}... "
            f"ip1={first_ip} ip2={ip} "
            f"within {DETECTION_WINDOW_SECONDS}s"
        )

    # Record this request
    _ip_activity[key].append((ip, now))
    return suspicious


def fire_webhook(
    webhook_url:  str,
    suspicious:   dict,
    email:        str,
    project_name: str,
) -> bool:
    """
    POST suspicious activity payload to the configured webhook URL.

    Payload is compatible with Slack incoming webhooks, Discord webhooks,
    and generic HTTP endpoints.
    """
    payload = {
        "event":              "suspicious_activity",
        "email":              email,
        "project_name":       project_name,
        "api_key_truncated":  suspicious.get("api_key_truncated"),
        "ip_original":        suspicious.get("ip_original"),
        "ip_new":             suspicious.get("ip_new"),
        "window_seconds":     suspicious.get("window_seconds"),
        "triggered_at":       suspicious.get("triggered_at"),
        "message": (
            f"⚠️ UDE Security Alert\n"
            f"Account: {email} ({project_name})\n"
            f"API key used from 2 different IPs within "
            f"{suspicious.get('window_seconds')}s:\n"
            f"  • {suspicious.get('ip_original')} (original)\n"
            f"  • {suspicious.get('ip_new')} (new)\n"
            f"If this wasn't you, rotate your key immediately:\n"
            f"  ude auth rotate"
        ),
    }

    # Slack-compatible format (works with Slack, Discord, most webhooks)
    slack_payload = {
        "text": payload["message"],
        "attachments": [{
            "color":  "danger",
            "fields": [
                {"title": "Email",        "value": email,                                    "short": True},
                {"title": "Project",      "value": project_name,                             "short": True},
                {"title": "API Key",      "value": suspicious.get("api_key_truncated"),      "short": True},
                {"title": "Original IP",  "value": suspicious.get("ip_original"),            "short": True},
                {"title": "New IP",       "value": suspicious.get("ip_new"),                 "short": True},
                {"title": "Triggered at", "value": suspicious.get("triggered_at", "")[:19], "short": True},
            ],
        }],
    }

    try:
        body = json.dumps(slack_payload).encode()
        req  = urllib.request.Request(
            webhook_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"[Webhook] Alert fired → {webhook_url[:40]}...")
        return True
    except Exception as exc:
        logger.error(f"[Webhook] Failed to fire webhook: {exc}")
        return False


def _load_webhook_url() -> Optional[str]:
    """Load webhook URL from ~/.ude/config.yml."""
    from pathlib import Path
    import yaml
    cfg_file = Path.home() / ".ude" / "config.yml"
    if not cfg_file.exists():
        return None
    try:
        with cfg_file.open() as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("webhook_url")
    except Exception:
        return None


def check_and_fire(
    api_key:      str,
    ip:           str,
    email:        str,
    project_name: str,
) -> None:
    """
    Main entry point called from auth middleware.
    Records the request, detects suspicious activity, fires webhook if configured.
    Non-blocking — all errors are caught and logged.
    """
    try:
        suspicious = record_request(api_key, ip)
        if not suspicious:
            return

        webhook_url = _load_webhook_url()
        if not webhook_url:
            logger.warning(
                "[Webhook] Suspicious activity detected but no webhook configured. "
                "Run: ude auth webhook-config"
            )
            return

        fire_webhook(
            webhook_url=webhook_url,
            suspicious=suspicious,
            email=email,
            project_name=project_name,
        )
    except Exception as exc:
        logger.error(f"[Webhook] check_and_fire error: {exc}")