"""Webhook alerting service for critical events.

Sends alerts to external webhook URLs (Discord, Slack, generic HTTP).
Alerts are fire-and-forget with short timeouts to avoid blocking callers.
"""

import logging
from datetime import UTC, datetime

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Short timeout for webhook calls — don't block the caller
_WEBHOOK_TIMEOUT = 5.0


async def send_alert(
    title: str,
    message: str,
    severity: str = "warning",
    details: dict | None = None,
) -> None:
    """Send an alert to the configured webhook URL.

    Silently fails if no webhook URL is configured or if the request fails.
    This is intentional — alerting should never break normal operations.

    Args:
        title: Short alert title
        message: Alert description
        severity: One of "info", "warning", "critical"
        details: Optional additional context
    """
    webhook_url = settings.alert_webhook_url
    if not webhook_url:
        return

    payload = _build_payload(title, message, severity, details, webhook_url)

    try:
        async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code >= 400:
                logger.warning("Webhook alert failed: HTTP %d", response.status_code)
    except Exception as e:
        logger.warning("Webhook alert failed: %s", e)


def _build_payload(
    title: str,
    message: str,
    severity: str,
    details: dict | None,
    webhook_url: str,
) -> dict:
    """Build webhook payload, adapting format for known services."""
    timestamp = datetime.now(UTC).isoformat()
    severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "❓")

    # Discord webhook format
    if "discord.com/api/webhooks" in webhook_url:
        content = f"{severity_emoji} **{title}**\n{message}"
        if details:
            content += "\n```json\n"
            import json

            content += json.dumps(details, indent=2)[:1500]
            content += "\n```"
        return {"content": content}

    # Slack webhook format
    if "hooks.slack.com" in webhook_url:
        text = f"{severity_emoji} *{title}*\n{message}"
        if details:
            import json

            text += f"\n```{json.dumps(details, indent=2)[:1500]}```"
        return {"text": text}

    # Generic webhook format
    return {
        "title": title,
        "message": message,
        "severity": severity,
        "timestamp": timestamp,
        "details": details or {},
        "source": "mcpbox",
    }
