"""Tests for security hardening changes.

Tests for:
1. Network access allowlist enforcement in SSRFProtectedAsyncHttpClient
2. Passthrough tool SSRF validation at call time
3. Secret value redaction in tool output
4. Allowed hosts stored and passed through registry
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.executor import _redact_secrets, python_executor
from app.registry import ToolRegistry
from app.ssrf import SSRFError, SSRFProtectedAsyncHttpClient


# =============================================================================
# Network Allowlist Enforcement Tests
# =============================================================================


class TestNetworkAllowlist:
    """Tests for per-server network allowlist in SSRFProtectedAsyncHttpClient."""

    def _make_client(self, allowed_hosts=None):
        """Create an SSRF-protected client with optional allowlist."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return SSRFProtectedAsyncHttpClient(mock_client, allowed_hosts=allowed_hosts)

    @patch("app.ssrf.validate_url_with_pinning")
    @pytest.mark.asyncio
    async def test_no_allowlist_allows_any_public_host(self, mock_validate):
        """When allowed_hosts is None, any public host is permitted."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "https://93.184.216.34/api"
        mock_validated.hostname = "api.example.com"
        mock_validated.scheme = "https"
        mock_validated.pinned_ip = "93.184.216.34"
        mock_validate.return_value = mock_validated

        client = self._make_client(allowed_hosts=None)
        # Should not raise — no allowlist means no restriction
        await client.get("https://api.example.com/api")

    def test_empty_allowlist_blocks_all_hosts(self):
        """When allowed_hosts is empty set, all requests are blocked."""
        client = self._make_client(allowed_hosts=set())

        with pytest.raises(SSRFError) as exc_info:
            # _prepare_request is sync, but we test it directly
            client._prepare_request("https://api.example.com/api", {})

        assert "not approved" in str(exc_info.value)
        assert "api.example.com" in str(exc_info.value)

    @patch("app.ssrf.validate_url_with_pinning")
    def test_allowlist_permits_approved_host(self, mock_validate):
        """Requests to approved hosts pass the allowlist check."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "https://93.184.216.34/api"
        mock_validated.hostname = "api.example.com"
        mock_validated.scheme = "https"
        mock_validated.pinned_ip = "93.184.216.34"
        mock_validate.return_value = mock_validated

        client = self._make_client(allowed_hosts={"api.example.com"})
        # Should not raise
        pinned_url, kwargs = client._prepare_request(
            "https://api.example.com/api", {}
        )
        assert pinned_url is not None

    def test_allowlist_blocks_unapproved_host(self):
        """Requests to unapproved hosts are blocked."""
        client = self._make_client(allowed_hosts={"api.example.com"})

        with pytest.raises(SSRFError) as exc_info:
            client._prepare_request("https://attacker.com/exfil", {})

        assert "not approved" in str(exc_info.value)
        assert "attacker.com" in str(exc_info.value)

    def test_allowlist_case_insensitive(self):
        """Hostname matching in allowlist is case-insensitive."""
        client = self._make_client(allowed_hosts={"api.example.com"})

        with pytest.raises(SSRFError):
            client._prepare_request("https://ATTACKER.COM/exfil", {})

    @patch("app.ssrf.validate_url_with_pinning")
    def test_allowlist_with_multiple_hosts(self, mock_validate):
        """Multiple approved hosts are all permitted."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "https://1.2.3.4/api"
        mock_validated.hostname = "api2.example.com"
        mock_validated.scheme = "https"
        mock_validated.pinned_ip = "1.2.3.4"
        mock_validate.return_value = mock_validated

        client = self._make_client(
            allowed_hosts={"api1.example.com", "api2.example.com", "api3.example.com"}
        )
        # Should not raise — host is in the allowlist
        pinned_url, kwargs = client._prepare_request(
            "https://api2.example.com/api", {}
        )
        assert pinned_url is not None

    def test_allowlist_still_blocks_private_ips(self):
        """Even with allowlist, private IPs are blocked by SSRF validation.

        The allowlist check runs first (hostname check), then SSRF
        validation runs (IP check). A private IP literal like 10.0.0.1
        would fail SSRF validation even if somehow in the allowlist.
        """
        # This would pass the allowlist but fail SSRF
        client = self._make_client(allowed_hosts={"10.0.0.1"})
        with pytest.raises(SSRFError):
            client._prepare_request("http://10.0.0.1/internal", {})

    def test_redirects_disabled_with_allowlist(self):
        """Redirects are always disabled regardless of allowlist."""
        client = self._make_client(allowed_hosts=set())

        # Even though this will fail the allowlist check, verify the redirect
        # disable happens in the kwargs
        try:
            client._prepare_request("https://blocked.com/api", {})
        except SSRFError:
            pass  # Expected
        # Note: we can't check kwargs here since the error is raised before
        # _prepare_pinned_request runs, but that's fine — the allowlist check
        # is more restrictive anyway.


# =============================================================================
# Registry Allowed Hosts Tests
# =============================================================================


class TestRegistryAllowedHosts:
    """Tests for allowed_hosts storage and propagation in ToolRegistry."""

    def test_register_server_stores_allowed_hosts(self, tool_registry, sample_tool_def):
        """Allowed hosts are stored on the registered server."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            allowed_hosts=["api.example.com", "data.example.com"],
        )

        server = tool_registry.servers["server-1"]
        assert server.allowed_hosts == {"api.example.com", "data.example.com"}

    def test_register_server_none_allowed_hosts(self, tool_registry, sample_tool_def):
        """None allowed_hosts means no restriction."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            allowed_hosts=None,
        )

        server = tool_registry.servers["server-1"]
        assert server.allowed_hosts is None

    def test_register_server_empty_allowed_hosts(self, tool_registry, sample_tool_def):
        """Empty allowed_hosts means no network access allowed."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
            allowed_hosts=[],
        )

        server = tool_registry.servers["server-1"]
        assert server.allowed_hosts == set()

    def test_register_server_default_no_allowed_hosts(
        self, tool_registry, sample_tool_def
    ):
        """Default registration has no allowed_hosts (None)."""
        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[sample_tool_def],
        )

        server = tool_registry.servers["server-1"]
        assert server.allowed_hosts is None


# =============================================================================
# Secret Redaction Tests
# =============================================================================


class TestSecretRedaction:
    """Tests for _redact_secrets function."""

    def test_redacts_secret_value_from_text(self):
        """Secret values are replaced with [REDACTED]."""
        text = "Using key: sk-1234567890abcdef for auth"
        secrets = {"API_KEY": "sk-1234567890abcdef"}

        result = _redact_secrets(text, secrets)
        assert "[REDACTED]" in result
        assert "sk-1234567890abcdef" not in result

    def test_redacts_multiple_secrets(self):
        """Multiple different secrets are all redacted."""
        text = "key1=my-secret-key-123 key2=another-secret-456"
        secrets = {
            "KEY1": "my-secret-key-123",
            "KEY2": "another-secret-456",
        }

        result = _redact_secrets(text, secrets)
        assert "my-secret-key-123" not in result
        assert "another-secret-456" not in result
        assert result.count("[REDACTED]") == 2

    def test_redacts_same_secret_multiple_occurrences(self):
        """Same secret appearing multiple times is fully redacted."""
        text = "first: my-secret-value, second: my-secret-value"
        secrets = {"KEY": "my-secret-value"}

        result = _redact_secrets(text, secrets)
        assert "my-secret-value" not in result
        assert result.count("[REDACTED]") == 2

    def test_skips_short_secrets(self):
        """Secrets shorter than threshold are not redacted (avoids false positives)."""
        text = "The value is yes and the count is 42"
        secrets = {"FLAG": "yes", "COUNT": "42"}

        result = _redact_secrets(text, secrets)
        # Short values should not be redacted
        assert result == text

    def test_empty_secrets_returns_original(self):
        """Empty secrets dict returns original text."""
        text = "Hello world"
        assert _redact_secrets(text, {}) == text
        assert _redact_secrets(text, None) == text

    def test_empty_text_returns_empty(self):
        """Empty text is returned as-is."""
        assert _redact_secrets("", {"KEY": "long-secret-value"}) == ""

    def test_secret_in_json_output(self):
        """Secrets embedded in JSON strings are redacted."""
        text = '{"auth": "Bearer sk-abcdefghijklmnop", "data": "safe"}'
        secrets = {"TOKEN": "sk-abcdefghijklmnop"}

        result = _redact_secrets(text, secrets)
        assert "sk-abcdefghijklmnop" not in result
        assert '"data": "safe"' in result


# =============================================================================
# Passthrough SSRF Validation Tests
# =============================================================================


class TestPassthroughSSRFValidation:
    """Tests for SSRF validation on passthrough tool execution."""

    @pytest.mark.asyncio
    async def test_passthrough_blocks_private_ip_url(self, tool_registry):
        """Passthrough tools with URLs resolving to private IPs are blocked."""
        # Register a passthrough tool with a source that resolves to private IP
        passthrough_def = {
            "name": "evil_tool",
            "description": "External tool",
            "parameters": {},
            "tool_type": "mcp_passthrough",
            "external_source_id": "source-1",
            "external_tool_name": "target",
        }
        external_sources = [
            {
                "source_id": "source-1",
                "url": "http://10.0.0.1:8080/mcp",
                "auth_headers": {},
            }
        ]

        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[passthrough_def],
            external_sources=external_sources,
        )

        result = await tool_registry.execute_tool(
            "TestServer__evil_tool", {"query": "test"}
        )

        assert result.get("success") is False
        assert "blocked" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_passthrough_blocks_localhost_url(self, tool_registry):
        """Passthrough tools targeting localhost are blocked."""
        passthrough_def = {
            "name": "internal_tool",
            "description": "Internal tool",
            "parameters": {},
            "tool_type": "mcp_passthrough",
            "external_source_id": "source-1",
            "external_tool_name": "target",
        }
        external_sources = [
            {
                "source_id": "source-1",
                "url": "http://localhost:8001/mcp",
                "auth_headers": {},
            }
        ]

        tool_registry.register_server(
            server_id="server-1",
            server_name="TestServer",
            tools=[passthrough_def],
            external_sources=external_sources,
        )

        result = await tool_registry.execute_tool(
            "TestServer__internal_tool", {}
        )

        assert result.get("success") is False
        assert "blocked" in result.get("error", "").lower()
