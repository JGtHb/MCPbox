"""Tests for webhook alerting service."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.webhook_alerting import _build_payload, send_alert


class TestBuildPayload:
    """Tests for webhook payload formatting."""

    def test_discord_payload(self):
        """Test Discord webhook format."""
        payload = _build_payload(
            "Test Alert",
            "Something happened",
            "warning",
            None,
            "https://discord.com/api/webhooks/123/abc",
        )
        assert "content" in payload
        assert "**Test Alert**" in payload["content"]
        assert "Something happened" in payload["content"]

    def test_slack_payload(self):
        """Test Slack webhook format."""
        payload = _build_payload(
            "Test Alert",
            "Something happened",
            "critical",
            None,
            "https://hooks.slack.com/services/T/B/x",
        )
        assert "text" in payload
        assert "*Test Alert*" in payload["text"]

    def test_generic_payload(self):
        """Test generic webhook format."""
        payload = _build_payload(
            "Test Alert",
            "Something happened",
            "info",
            {"key": "value"},
            "https://example.com/webhook",
        )
        assert payload["title"] == "Test Alert"
        assert payload["message"] == "Something happened"
        assert payload["severity"] == "info"
        assert payload["source"] == "mcpbox"
        assert payload["details"] == {"key": "value"}


class TestSendAlert:
    """Tests for send_alert function."""

    @pytest.mark.asyncio
    async def test_no_webhook_url_is_noop(self):
        """Test that send_alert is a no-op when webhook URL is empty."""
        with patch("app.services.webhook_alerting.settings") as mock_settings:
            mock_settings.alert_webhook_url = ""
            # Should not raise
            await send_alert("Test", "Message")

    @pytest.mark.asyncio
    async def test_webhook_failure_does_not_raise(self):
        """Test that webhook failures are silently handled."""
        with patch("app.services.webhook_alerting.settings") as mock_settings:
            mock_settings.alert_webhook_url = "https://example.com/webhook"
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(side_effect=Exception("Network error"))
                mock_client_cls.return_value = mock_client
                # Should not raise
                await send_alert("Test", "Message")
