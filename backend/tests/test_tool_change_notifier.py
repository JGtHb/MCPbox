"""Tests for tool change notifier service."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.tool_change_notifier import (
    MCP_GATEWAY_URL,
    fire_and_forget_notify,
    notify_tools_changed_local,
    notify_tools_changed_via_gateway,
)

pytestmark = pytest.mark.asyncio


class TestNotifyToolsChangedViaGateway:
    """Tests for cross-process notification via HTTP."""

    async def test_successful_notification(self):
        """Sends POST to gateway and logs success on 200."""
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("app.services.tool_change_notifier.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            await notify_tools_changed_via_gateway()

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "/mcp/internal/notify-tools-changed" in call_args[0][0]
            assert call_args.kwargs["timeout"] == 2.0

    async def test_includes_auth_header_when_configured(self):
        """Authorization header is included when sandbox_api_key is set."""
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("app.services.tool_change_notifier.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            with patch("app.services.tool_change_notifier.settings") as mock_settings:
                mock_settings.sandbox_api_key = "test-key"
                await notify_tools_changed_via_gateway()

            call_args = mock_client.post.call_args
            headers = call_args.kwargs.get("headers") or call_args[1].get("headers", {})
            assert headers.get("Authorization") == "Bearer test-key"

    async def test_connection_error_does_not_raise(self):
        """ConnectError is handled gracefully (gateway not running)."""
        import httpx

        with patch("app.services.tool_change_notifier.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            # Should not raise
            await notify_tools_changed_via_gateway()

    async def test_unexpected_error_does_not_raise(self):
        """Unexpected errors are logged but never propagated."""
        with patch("app.services.tool_change_notifier.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = RuntimeError("unexpected")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            # Should not raise
            await notify_tools_changed_via_gateway()

    async def test_non_200_response_does_not_raise(self):
        """Non-200 responses are logged but don't propagate."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("app.services.tool_change_notifier.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            # Should not raise
            await notify_tools_changed_via_gateway()


class TestFireAndForgetNotify:
    """Tests for fire-and-forget background task scheduling."""

    async def test_creates_background_task(self):
        """fire_and_forget_notify creates an asyncio task."""
        with patch(
            "app.services.tool_change_notifier.notify_tools_changed_via_gateway",
            new_callable=AsyncMock,
        ) as mock_notify:
            fire_and_forget_notify()
            # Give the task a chance to start
            import asyncio

            await asyncio.sleep(0.01)
            mock_notify.assert_called_once()


class TestNotifyToolsChangedLocal:
    """Tests for same-process (MCP gateway) notification."""

    async def test_calls_broadcast_directly(self):
        """notify_tools_changed_local calls broadcast_tools_changed."""
        with patch(
            "app.api.mcp_gateway.broadcast_tools_changed",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await notify_tools_changed_local()
            mock_broadcast.assert_called_once()
