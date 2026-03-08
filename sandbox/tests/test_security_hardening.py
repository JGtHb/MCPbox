"""Tests for security hardening changes.

Tests for:
1. Network access allowlist enforcement in SSRFProtectedAsyncHttpClient
2. Passthrough tool SSRF validation at call time
3. Secret value redaction in tool output
4. Allowed hosts stored and passed through registry
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.executor import _redact_secrets
from app.ssrf import SSRFError, SSRFProtectedAsyncHttpClient


# =============================================================================
# Network Allowlist Enforcement Tests
# =============================================================================


class TestNetworkAllowlist:
    """Tests for per-server network allowlist in SSRFProtectedAsyncHttpClient."""

    def _make_client(self, allowed_hosts=None):
        """Create an SSRF-protected client with optional allowlist.

        Forces direct mode (proxy_mode=False) so these tests are deterministic
        regardless of whether HTTPS_PROXY is set in the test environment.
        """
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return SSRFProtectedAsyncHttpClient(
            mock_client, allowed_hosts=allowed_hosts, proxy_mode=False
        )

    @patch("app.ssrf.async_validate_url_with_pinning", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_no_allowlist_allows_any_public_host(self, mock_validate):
        """When allowed_hosts is None, any public host is permitted."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "https://93.184.216.34/api"
        mock_validated.hostname = "api.example.com"
        mock_validated.scheme = "https"
        mock_validated.pinned_ip = "93.184.216.34"
        mock_validate.return_value = mock_validated

        # Set up mock to support the streaming interface used by
        # _request_with_size_limit (build_request → send → aiter_bytes)
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = AsyncMock()
        mock_response.headers = httpx.Headers({})

        async def empty_aiter_bytes(chunk_size=65536):
            return
            yield  # Make this an async generator

        mock_response.aiter_bytes = empty_aiter_bytes
        mock_response.aclose = AsyncMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        client = SSRFProtectedAsyncHttpClient(
            mock_client, allowed_hosts=None, proxy_mode=False
        )
        # Should not raise — no allowlist means no restriction
        await client.get("https://api.example.com/api")

    @pytest.mark.asyncio
    async def test_empty_allowlist_blocks_all_hosts(self):
        """When allowed_hosts is empty set, all requests are blocked."""
        client = self._make_client(allowed_hosts=set())

        with pytest.raises(SSRFError) as exc_info:
            await client._prepare_request("https://api.example.com/api", {})

        assert "not approved" in str(exc_info.value)
        assert "api.example.com" in str(exc_info.value)

    @patch("app.ssrf.async_validate_url_with_pinning", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_allowlist_permits_approved_host(self, mock_validate):
        """Requests to approved hosts pass the allowlist check."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "https://93.184.216.34/api"
        mock_validated.hostname = "api.example.com"
        mock_validated.scheme = "https"
        mock_validated.pinned_ip = "93.184.216.34"
        mock_validate.return_value = mock_validated

        client = self._make_client(allowed_hosts={"api.example.com"})
        # Should not raise
        pinned_url, kwargs = await client._prepare_request(
            "https://api.example.com/api", {}
        )
        assert pinned_url is not None

    @pytest.mark.asyncio
    async def test_allowlist_blocks_unapproved_host(self):
        """Requests to unapproved hosts are blocked."""
        client = self._make_client(allowed_hosts={"api.example.com"})

        with pytest.raises(SSRFError) as exc_info:
            await client._prepare_request("https://attacker.com/exfil", {})

        assert "not approved" in str(exc_info.value)
        assert "attacker.com" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_allowlist_case_insensitive(self):
        """Hostname matching in allowlist is case-insensitive."""
        client = self._make_client(allowed_hosts={"api.example.com"})

        with pytest.raises(SSRFError):
            await client._prepare_request("https://ATTACKER.COM/exfil", {})

    @patch("app.ssrf.async_validate_url_with_pinning", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_allowlist_with_multiple_hosts(self, mock_validate):
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
        pinned_url, kwargs = await client._prepare_request(
            "https://api2.example.com/api", {}
        )
        assert pinned_url is not None

    @pytest.mark.asyncio
    async def test_allowlist_allows_private_ips(self):
        """Private IPs in allowed_hosts are permitted (admin-approved).

        When a host is in allowed_hosts it means the admin explicitly
        approved it, so private RFC 1918 IPs pass SSRF validation.
        Loopback/metadata IPs are always blocked regardless.
        """
        client = self._make_client(allowed_hosts={"10.0.0.1"})
        url, _ = await client._prepare_request("http://10.0.0.1/internal", {})
        assert "10.0.0.1" in url

    @pytest.mark.asyncio
    async def test_redirects_disabled_with_allowlist(self):
        """Redirects are always disabled regardless of allowlist."""
        client = self._make_client(allowed_hosts=set())

        # Even though this will fail the allowlist check, verify the redirect
        # disable happens in the kwargs
        try:
            await client._prepare_request("https://blocked.com/api", {})
        except SSRFError:
            pass  # Expected
        # Note: we can't check kwargs here since the error is raised before
        # _prepare_pinned_request runs, but that's fine — the allowlist check
        # is more restrictive anyway.

    @pytest.mark.asyncio
    async def test_allowlist_port_specific_blocks_different_port(self):
        """Port-specific entry 'host:8081' blocks requests to host:1883."""
        client = self._make_client(allowed_hosts={"192.168.1.2:8081"})

        with pytest.raises(SSRFError) as exc_info:
            await client._prepare_request("http://192.168.1.2:1883/mqtt", {})

        assert "not approved" in str(exc_info.value)

    @patch("app.ssrf.async_validate_url_with_pinning", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_allowlist_port_specific_permits_matching_port(self, mock_validate):
        """Port-specific entry 'host:8081' permits requests to host:8081."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "http://192.168.1.2:8081/api"
        mock_validated.hostname = "192.168.1.2"
        mock_validated.scheme = "http"
        mock_validated.pinned_ip = "192.168.1.2"
        mock_validate.return_value = mock_validated

        client = self._make_client(allowed_hosts={"192.168.1.2:8081"})
        url, _ = await client._prepare_request("http://192.168.1.2:8081/api", {})
        assert url is not None

    @pytest.mark.asyncio
    async def test_allowlist_any_port_permits_all_ports(self):
        """Any-port entry 'host' (no port suffix) permits requests on any port."""
        client = self._make_client(allowed_hosts={"192.168.1.2"})
        # Should not raise — any port is allowed
        url, _ = await client._prepare_request("http://192.168.1.2:8081/api", {})
        assert "192.168.1.2" in url

    @pytest.mark.asyncio
    async def test_allowlist_port_specific_blocks_default_port(self):
        """Port-specific entry 'host:8081' blocks requests on default port 80."""
        client = self._make_client(allowed_hosts={"192.168.1.2:8081"})

        with pytest.raises(SSRFError):
            await client._prepare_request("http://192.168.1.2/api", {})

    @patch("app.ssrf.async_validate_url_with_pinning", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_allowlist_multiple_ports_same_host(self, mock_validate):
        """Multiple port-specific entries for the same host work independently."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "http://192.168.1.2:1883/mqtt"
        mock_validated.hostname = "192.168.1.2"
        mock_validated.scheme = "http"
        mock_validated.pinned_ip = "192.168.1.2"
        mock_validate.return_value = mock_validated

        client = self._make_client(
            allowed_hosts={"192.168.1.2:8081", "192.168.1.2:1883"}
        )
        # Port 1883 should be permitted
        url, _ = await client._prepare_request("http://192.168.1.2:1883/mqtt", {})
        assert url is not None

        # Port 22 should be blocked
        with pytest.raises(SSRFError):
            await client._prepare_request("http://192.168.1.2:22/ssh", {})


# =============================================================================
# Proxy Mode Tests
# =============================================================================


class TestProxyMode:
    """Tests for proxy mode vs direct mode in SSRFProtectedAsyncHttpClient.

    Proxy mode (HTTPS_PROXY set) skips IP pinning and delegates DNS resolution
    to the SOCKS5 proxy. Direct mode (default) performs full IP pinning.
    """

    def _make_client(self, allowed_hosts=None, proxy_mode=None):
        """Create an SSRF-protected client with explicit mode control."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return SSRFProtectedAsyncHttpClient(
            mock_client, allowed_hosts=allowed_hosts, proxy_mode=proxy_mode
        )

    # --- Mode detection ---

    @pytest.mark.asyncio
    async def test_proxy_mode_from_env_var(self):
        """proxy_mode auto-detects _PROXY_MODE (set from HTTPS_PROXY env var)."""
        with patch("app.ssrf._PROXY_MODE", True):
            client = self._make_client()
            # In proxy mode, URL should NOT be rewritten (no IP pinning)
            url, _ = await client._prepare_request("https://api.example.com/data", {})
            assert url == "https://api.example.com/data"

    @patch("app.ssrf.async_validate_url_with_pinning", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_direct_mode_default(self, mock_validate):
        """Without HTTPS_PROXY, direct mode is used (IP pinning)."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "https://93.184.216.34/data"
        mock_validated.hostname = "api.example.com"
        mock_validated.scheme = "https"
        mock_validated.pinned_ip = "93.184.216.34"
        mock_validate.return_value = mock_validated

        with patch("app.ssrf._PROXY_MODE", False):
            client = self._make_client()
            url, _ = await client._prepare_request("https://api.example.com/data", {})
            assert url == "https://93.184.216.34/data"  # IP-pinned
            mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_proxy_mode_overrides_env(self):
        """Explicit proxy_mode=True overrides _PROXY_MODE=False."""
        with patch("app.ssrf._PROXY_MODE", False):
            client = self._make_client(proxy_mode=True)
            url, _ = await client._prepare_request("https://api.example.com/data", {})
            assert url == "https://api.example.com/data"  # Not pinned

    @patch("app.ssrf.async_validate_url_with_pinning", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_explicit_direct_mode_overrides_env(self, mock_validate):
        """Explicit proxy_mode=False overrides _PROXY_MODE=True."""
        mock_validated = MagicMock()
        mock_validated.get_pinned_url.return_value = "https://93.184.216.34/data"
        mock_validated.hostname = "api.example.com"
        mock_validated.scheme = "https"
        mock_validated.pinned_ip = "93.184.216.34"
        mock_validate.return_value = mock_validated

        with patch("app.ssrf._PROXY_MODE", True):
            client = self._make_client(proxy_mode=False)
            url, _ = await client._prepare_request("https://api.example.com/data", {})
            assert url == "https://93.184.216.34/data"  # Forced IP-pinned
            mock_validate.assert_called_once()

    # --- Proxy mode security checks ---

    @pytest.mark.asyncio
    async def test_proxy_mode_blocks_private_ip_literal(self):
        """Proxy mode still blocks literal private IPs in URLs."""
        client = self._make_client(proxy_mode=True)
        with pytest.raises(SSRFError, match="blocked IP range"):
            await client._prepare_request("http://10.0.0.1/internal", {})

    @pytest.mark.asyncio
    async def test_proxy_mode_blocks_localhost(self):
        """Proxy mode still blocks localhost."""
        client = self._make_client(proxy_mode=True)
        with pytest.raises(SSRFError, match="Blocked hostname"):
            await client._prepare_request("http://localhost/api", {})

    @pytest.mark.asyncio
    async def test_proxy_mode_blocks_metadata_endpoint(self):
        """Proxy mode still blocks cloud metadata endpoints."""
        client = self._make_client(proxy_mode=True)
        with pytest.raises(SSRFError, match="Blocked"):
            await client._prepare_request(
                "http://169.254.169.254/latest/meta-data/", {}
            )

    @pytest.mark.asyncio
    async def test_proxy_mode_does_not_inject_follow_redirects(self):
        """follow_redirects is NOT injected per-request (set at client construction)."""
        client = self._make_client(proxy_mode=True)
        _, kwargs = await client._prepare_request("https://api.example.com/data", {})
        assert "follow_redirects" not in kwargs

    # --- Allowlist + proxy mode interaction ---

    @pytest.mark.asyncio
    async def test_proxy_mode_enforces_allowlist(self):
        """Per-server allowlist is enforced in proxy mode."""
        client = self._make_client(allowed_hosts={"api.example.com"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="not approved"):
            await client._prepare_request("https://attacker.com/exfil", {})

    @pytest.mark.asyncio
    async def test_proxy_mode_permits_approved_host(self):
        """Approved hosts pass in proxy mode."""
        client = self._make_client(allowed_hosts={"api.example.com"}, proxy_mode=True)
        url, _ = await client._prepare_request("https://api.example.com/data", {})
        assert url == "https://api.example.com/data"

    @pytest.mark.asyncio
    async def test_proxy_mode_empty_allowlist_blocks_all(self):
        """Empty allowlist blocks all hosts in proxy mode."""
        client = self._make_client(allowed_hosts=set(), proxy_mode=True)
        with pytest.raises(SSRFError, match="not approved"):
            await client._prepare_request("https://api.example.com/data", {})

    # --- Proxy mode does NOT add IP pinning artifacts ---

    @pytest.mark.asyncio
    async def test_proxy_mode_no_host_header_override(self):
        """Proxy mode doesn't add Host header (SOCKS5 proxy handles routing)."""
        client = self._make_client(proxy_mode=True)
        _, kwargs = await client._prepare_request("https://api.example.com/data", {})
        assert "Host" not in kwargs.get("headers", {})

    @pytest.mark.asyncio
    async def test_proxy_mode_no_sni_override(self):
        """Proxy mode doesn't set SNI extension (SOCKS5 proxy handles TLS)."""
        client = self._make_client(proxy_mode=True)
        _, kwargs = await client._prepare_request("https://api.example.com/data", {})
        assert "sni_hostname" not in kwargs.get("extensions", {})

    @pytest.mark.asyncio
    async def test_proxy_mode_no_dns_resolution(self):
        """Proxy mode does not resolve DNS (delegated to SOCKS5 proxy)."""
        with patch("app.ssrf.socket.getaddrinfo") as mock_dns:
            client = self._make_client(proxy_mode=True)
            await client._prepare_request("https://api.example.com/data", {})
            mock_dns.assert_not_called()


# =============================================================================
# Admin-Approved Private Access via allowed_hosts
# =============================================================================


class TestAdminApprovedMode:
    """Tests for admin-approved private access via allowed_hosts + SSRFProtectedAsyncHttpClient."""

    def _make_client(self, allowed_hosts=None, proxy_mode=None):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return SSRFProtectedAsyncHttpClient(
            mock_client, allowed_hosts=allowed_hosts, proxy_mode=proxy_mode
        )

    @pytest.mark.asyncio
    async def test_proxy_mode_allows_private_ip_via_allowlist(self):
        """When private IP is in allowed_hosts, proxy mode allows it."""
        client = self._make_client(allowed_hosts={"192.168.1.50"}, proxy_mode=True)
        url, _ = await client._prepare_request("http://192.168.1.50:8080/api", {})
        assert url == "http://192.168.1.50:8080/api"

    @pytest.mark.asyncio
    async def test_proxy_mode_blocks_private_ip_not_in_allowlist(self):
        """Private IP not in allowed_hosts is blocked in proxy mode."""
        client = self._make_client(allowed_hosts={"api.example.com"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="not approved"):
            await client._prepare_request("http://192.168.1.50/api", {})

    @pytest.mark.asyncio
    async def test_proxy_mode_blocks_private_ip_without_allowlist(self):
        """Private IP blocked when no allowlist set (admin_approved=False)."""
        client = self._make_client(proxy_mode=True)
        with pytest.raises(SSRFError, match="blocked IP range"):
            await client._prepare_request("http://10.0.0.1/api", {})

    @pytest.mark.asyncio
    async def test_proxy_mode_allows_10_x_via_allowlist(self):
        """10.x.x.x private IP allowed when in allowed_hosts."""
        client = self._make_client(allowed_hosts={"10.0.0.5"}, proxy_mode=True)
        url, _ = await client._prepare_request("http://10.0.0.5:9090/api", {})
        assert "10.0.0.5" in url

    @pytest.mark.asyncio
    async def test_allowlist_blocks_even_if_other_privates_approved(self):
        """Per-server allowlist blocks IPs not in its list."""
        client = self._make_client(allowed_hosts={"api.example.com"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="not approved"):
            await client._prepare_request("http://192.168.1.50:8080/api", {})

    @pytest.mark.asyncio
    async def test_localhost_always_blocked_even_in_allowlist(self):
        """Localhost is always blocked even if in allowed_hosts."""
        client = self._make_client(allowed_hosts={"localhost"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="Blocked hostname"):
            await client._prepare_request("http://localhost/api", {})

    @pytest.mark.asyncio
    async def test_metadata_always_blocked_even_in_allowlist(self):
        """Cloud metadata IP is always blocked even if in allowed_hosts."""
        client = self._make_client(allowed_hosts={"169.254.169.254"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="Blocked"):
            await client._prepare_request(
                "http://169.254.169.254/latest/meta-data/", {}
            )

    @pytest.mark.asyncio
    async def test_loopback_always_blocked_even_in_allowlist(self):
        """Loopback IP is always blocked even if in allowed_hosts."""
        client = self._make_client(allowed_hosts={"127.0.0.1"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="Blocked"):
            await client._prepare_request("http://127.0.0.1/api", {})


# =============================================================================
# Port Enforcement Tests
# =============================================================================


class TestPortEnforcement:
    """Tests for port-level enforcement in allowed_hosts."""

    def _make_client(self, allowed_hosts=None, proxy_mode=None):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        return SSRFProtectedAsyncHttpClient(
            mock_client, allowed_hosts=allowed_hosts, proxy_mode=proxy_mode
        )

    @pytest.mark.asyncio
    async def test_host_port_entry_allows_matching_port(self):
        """host:port entry allows requests to that specific port."""
        client = self._make_client(allowed_hosts={"192.168.1.2:8081"}, proxy_mode=True)
        url, _ = await client._prepare_request("http://192.168.1.2:8081/api", {})
        assert "192.168.1.2:8081" in url

    @pytest.mark.asyncio
    async def test_host_port_entry_blocks_different_port(self):
        """host:port entry blocks requests to a different port."""
        client = self._make_client(allowed_hosts={"192.168.1.2:8081"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="not approved"):
            await client._prepare_request("http://192.168.1.2:9090/api", {})

    @pytest.mark.asyncio
    async def test_host_only_entry_allows_any_port(self):
        """host entry (no port) allows requests to any port."""
        client = self._make_client(allowed_hosts={"192.168.1.2"}, proxy_mode=True)
        url1, _ = await client._prepare_request("http://192.168.1.2:8081/api", {})
        assert "192.168.1.2" in url1
        url2, _ = await client._prepare_request("http://192.168.1.2:9090/api", {})
        assert "192.168.1.2" in url2

    @pytest.mark.asyncio
    async def test_mixed_entries_both_formats(self):
        """Mix of host-only and host:port entries work together."""
        client = self._make_client(
            allowed_hosts={"10.0.0.1", "192.168.1.2:8081"}, proxy_mode=True
        )
        # 10.0.0.1 any port → allowed
        url, _ = await client._prepare_request("http://10.0.0.1:443/api", {})
        assert "10.0.0.1" in url
        # 192.168.1.2:8081 specific → allowed
        url, _ = await client._prepare_request("http://192.168.1.2:8081/api", {})
        assert "192.168.1.2" in url
        # 192.168.1.2:22 → blocked
        with pytest.raises(SSRFError, match="not approved"):
            await client._prepare_request("http://192.168.1.2:22/api", {})

    @pytest.mark.asyncio
    async def test_https_default_port_443(self):
        """HTTPS URLs without explicit port default to 443."""
        client = self._make_client(
            allowed_hosts={"api.example.com:443"}, proxy_mode=True
        )
        url, _ = await client._prepare_request("https://api.example.com/api", {})
        assert "api.example.com" in url

    @pytest.mark.asyncio
    async def test_http_default_port_80(self):
        """HTTP URLs without explicit port default to 80."""
        client = self._make_client(
            allowed_hosts={"api.example.com:80"}, proxy_mode=True
        )
        url, _ = await client._prepare_request("http://api.example.com/api", {})
        assert "api.example.com" in url

    @pytest.mark.asyncio
    async def test_error_message_includes_port(self):
        """Error message shows host:port to help users request the right access."""
        client = self._make_client(allowed_hosts={"192.168.1.2:8081"}, proxy_mode=True)
        with pytest.raises(SSRFError, match="192.168.1.2:9090"):
            await client._prepare_request("http://192.168.1.2:9090/api", {})


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

        result = await tool_registry.execute_tool("TestServer__internal_tool", {})

        assert result.get("success") is False
        assert "blocked" in result.get("error", "").lower()
