"""Unit tests for URL validation (SSRF prevention)."""

from unittest.mock import patch

import pytest

from app.ssrf import (
    SSRFError,
    _is_always_blocked_ip,
    _validate_hostname_only,
    validate_url_with_pinning,
)


# Mock socket.getaddrinfo to avoid actual DNS resolution in tests
def mock_getaddrinfo(host, port, *args, **kwargs):
    """Return a mock public IP for test domains."""
    return [(2, 1, 6, "", ("93.184.216.34", port))]  # example.com's actual IP


class TestValidateUrl:
    """Tests for the validate_url_with_pinning function."""

    # --- Valid URLs ---

    @patch("socket.getaddrinfo", mock_getaddrinfo)
    def test_valid_https_url(self):
        """HTTPS URLs are accepted."""
        url = "https://api.example.com/v1/data"
        result = validate_url_with_pinning(url)
        assert result.original_url == url

    @patch("socket.getaddrinfo", mock_getaddrinfo)
    def test_valid_http_url(self):
        """HTTP URLs are accepted."""
        url = "http://api.example.com/v1/data"
        result = validate_url_with_pinning(url)
        assert result.original_url == url

    @patch("socket.getaddrinfo", mock_getaddrinfo)
    def test_url_with_port(self):
        """URLs with ports are accepted."""
        url = "https://api.example.com:8443/v1/data"
        result = validate_url_with_pinning(url)
        assert result.original_url == url

    @patch("socket.getaddrinfo", mock_getaddrinfo)
    def test_url_with_query_params(self):
        """URLs with query params are accepted."""
        url = "https://api.example.com/search?q=test&limit=10"
        result = validate_url_with_pinning(url)
        assert result.original_url == url

    @patch("socket.getaddrinfo", mock_getaddrinfo)
    def test_url_with_path(self):
        """URLs with paths are accepted."""
        url = "https://api.example.com/v1/users/123/profile"
        result = validate_url_with_pinning(url)
        assert result.original_url == url

    # --- Invalid Schemes ---

    def test_empty_url_rejected(self):
        """Empty URL is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("")
        assert "cannot be empty" in str(exc_info.value)

    def test_ftp_scheme_rejected(self):
        """FTP scheme is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("ftp://files.example.com/data")
        assert "Invalid scheme" in str(exc_info.value)

    def test_file_scheme_rejected(self):
        """File scheme is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("file:///etc/passwd")
        assert "Invalid scheme" in str(exc_info.value)

    def test_javascript_scheme_rejected(self):
        """JavaScript scheme is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("javascript:alert(1)")
        assert "Invalid scheme" in str(exc_info.value)

    def test_data_scheme_rejected(self):
        """Data scheme is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("data:text/html,<script>alert(1)</script>")
        assert "Invalid scheme" in str(exc_info.value)

    # --- Blocked Hostnames ---

    def test_localhost_rejected(self):
        """localhost is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://localhost/api")
        assert "Blocked hostname" in str(exc_info.value)

    def test_127_0_0_1_rejected(self):
        """127.0.0.1 is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://127.0.0.1/api")
        # 127.0.0.1 is in BLOCKED_HOSTNAMES, so it's caught as blocked hostname
        assert "Blocked" in str(exc_info.value)

    def test_0_0_0_0_rejected(self):
        """0.0.0.0 is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://0.0.0.0/api")
        assert "Blocked hostname" in str(exc_info.value)

    def test_ipv6_localhost_rejected(self):
        """IPv6 localhost is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://[::1]/api")
        assert "Blocked" in str(exc_info.value)

    # --- Cloud Metadata Endpoints ---

    def test_aws_metadata_rejected(self):
        """AWS metadata endpoint is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://169.254.169.254/latest/meta-data/")
        assert "Blocked" in str(exc_info.value)

    def test_gcp_metadata_rejected(self):
        """GCP metadata endpoint is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning(
                "http://metadata.google.internal/computeMetadata/v1/"
            )
        assert "Blocked" in str(exc_info.value)

    # --- Private IP Ranges ---

    def test_10_x_x_x_rejected(self):
        """10.x.x.x private range is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://10.0.0.1/api")
        assert "blocked IP range" in str(exc_info.value)

    def test_172_16_x_x_rejected(self):
        """172.16.x.x private range is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://172.16.0.1/api")
        assert "blocked IP range" in str(exc_info.value)

    def test_192_168_x_x_rejected(self):
        """192.168.x.x private range is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://192.168.1.1/api")
        assert "blocked IP range" in str(exc_info.value)

    def test_link_local_rejected(self):
        """Link-local addresses are rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://169.254.1.1/api")
        assert "blocked IP range" in str(exc_info.value)

    # --- Edge Cases ---

    def test_public_ip_accepted(self):
        """Public IP addresses are accepted."""
        url = "http://8.8.8.8/dns"
        result = validate_url_with_pinning(url)
        assert result.original_url == url

    @patch("socket.getaddrinfo", mock_getaddrinfo)
    def test_url_with_username_password(self):
        """URLs with credentials are handled."""
        url = "https://user:pass@api.example.com/data"
        result = validate_url_with_pinning(url)
        assert result.original_url == url

    def test_url_missing_hostname_rejected(self):
        """URL without hostname is rejected."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http:///path/only")
        assert "must have a hostname" in str(exc_info.value)

    def test_case_insensitive_hostname_blocking(self):
        """Hostname blocking is case-insensitive."""
        with pytest.raises(SSRFError) as exc_info:
            validate_url_with_pinning("http://LOCALHOST/api")
        assert "Blocked hostname" in str(exc_info.value)


class TestValidateHostnameOnly:
    """Tests for proxy-mode hostname validation (no IP pinning, no DNS).

    In proxy mode, DNS resolution and private IP blocking are delegated to
    the squid proxy. This function only validates hostnames and literal IPs
    client-side, returning the original URL unchanged.
    """

    # --- Valid URLs (returned unchanged, no DNS resolution) ---

    def test_valid_https_url_returned_unchanged(self):
        """HTTPS URL is returned without IP rewriting."""
        url = "https://api.example.com/v1/data"
        result_url, _ = _validate_hostname_only(url, {})
        assert result_url == url

    def test_valid_http_url_accepted(self):
        """HTTP URL is accepted and returned unchanged."""
        url = "http://api.example.com/v1/data"
        result_url, _ = _validate_hostname_only(url, {})
        assert result_url == url

    def test_url_with_port(self):
        """URLs with ports are accepted."""
        url = "https://api.example.com:8443/v1/data"
        result_url, _ = _validate_hostname_only(url, {})
        assert result_url == url

    def test_url_with_query_params(self):
        """URLs with query params are accepted."""
        url = "https://api.example.com/search?q=test&limit=10"
        result_url, _ = _validate_hostname_only(url, {})
        assert result_url == url

    def test_public_ip_accepted(self):
        """Public IP addresses are accepted."""
        url = "https://8.8.8.8/dns"
        result_url, _ = _validate_hostname_only(url, {})
        assert result_url == url

    # --- Invalid/empty URLs ---

    def test_empty_url_rejected(self):
        """Empty URL is rejected."""
        with pytest.raises(SSRFError, match="cannot be empty"):
            _validate_hostname_only("", {})

    def test_missing_hostname_rejected(self):
        """URL without hostname is rejected."""
        with pytest.raises(SSRFError, match="must have a hostname"):
            _validate_hostname_only("http:///path/only", {})

    # --- Invalid schemes ---

    def test_ftp_scheme_rejected(self):
        """FTP scheme is rejected."""
        with pytest.raises(SSRFError, match="Invalid scheme"):
            _validate_hostname_only("ftp://files.example.com/data", {})

    def test_file_scheme_rejected(self):
        """File scheme is rejected."""
        with pytest.raises(SSRFError, match="Invalid scheme"):
            _validate_hostname_only("file:///etc/passwd", {})

    def test_data_scheme_rejected(self):
        """Data scheme is rejected."""
        with pytest.raises(SSRFError, match="Invalid scheme"):
            _validate_hostname_only("data:text/html,<script>alert(1)</script>", {})

    # --- Blocked hostnames ---

    def test_localhost_rejected(self):
        """localhost is rejected."""
        with pytest.raises(SSRFError, match="Blocked hostname"):
            _validate_hostname_only("http://localhost/api", {})

    def test_127_0_0_1_rejected(self):
        """127.0.0.1 is rejected (in BLOCKED_HOSTNAMES)."""
        with pytest.raises(SSRFError, match="Blocked"):
            _validate_hostname_only("http://127.0.0.1/api", {})

    def test_metadata_endpoint_rejected(self):
        """AWS metadata endpoint is rejected."""
        with pytest.raises(SSRFError, match="Blocked"):
            _validate_hostname_only("http://169.254.169.254/latest/meta-data/", {})

    def test_gcp_metadata_rejected(self):
        """GCP metadata endpoint is rejected."""
        with pytest.raises(SSRFError, match="Blocked"):
            _validate_hostname_only(
                "http://metadata.google.internal/computeMetadata/v1/", {}
            )

    def test_case_insensitive_blocking(self):
        """Hostname blocking is case-insensitive."""
        with pytest.raises(SSRFError, match="Blocked hostname"):
            _validate_hostname_only("http://LOCALHOST/api", {})

    # --- Literal private IPs blocked ---

    def test_10_x_x_x_literal_rejected(self):
        """10.x.x.x private IP literal is rejected."""
        with pytest.raises(SSRFError, match="blocked IP range"):
            _validate_hostname_only("http://10.0.0.1/api", {})

    def test_172_16_x_x_literal_rejected(self):
        """172.16.x.x private IP literal is rejected."""
        with pytest.raises(SSRFError, match="blocked IP range"):
            _validate_hostname_only("http://172.16.0.1/api", {})

    def test_192_168_x_x_literal_rejected(self):
        """192.168.x.x private IP literal is rejected."""
        with pytest.raises(SSRFError, match="blocked IP range"):
            _validate_hostname_only("http://192.168.1.1/api", {})

    def test_link_local_literal_rejected(self):
        """Link-local IP literal is rejected."""
        with pytest.raises(SSRFError, match="blocked IP range"):
            _validate_hostname_only("http://169.254.1.1/api", {})

    # --- Key difference from direct mode: no DNS resolution ---

    def test_no_dns_resolution_performed(self):
        """Hostname URLs don't trigger DNS — that's delegated to squid."""
        with patch("app.ssrf.socket.getaddrinfo") as mock_dns:
            url = "https://api.example.com/v1/data"
            result_url, _ = _validate_hostname_only(url, {})
            mock_dns.assert_not_called()
            assert result_url == url

    def test_kwargs_passed_through(self):
        """Extra kwargs are returned unchanged."""
        kwargs = {"timeout": 30, "headers": {"Accept": "application/json"}}
        _, result_kwargs = _validate_hostname_only("https://example.com/api", kwargs)
        assert result_kwargs["timeout"] == 30
        assert result_kwargs["headers"]["Accept"] == "application/json"


# =============================================================================
# _is_always_blocked_ip — Unit Tests
# =============================================================================


class TestIsAlwaysBlockedIp:
    """Tests for _is_always_blocked_ip helper."""

    def test_loopback_blocked(self):
        """127.x.x.x is always blocked."""
        assert _is_always_blocked_ip("127.0.0.1") is True
        assert _is_always_blocked_ip("127.255.255.255") is True

    def test_link_local_blocked(self):
        """169.254.x.x (cloud metadata) is always blocked."""
        assert _is_always_blocked_ip("169.254.169.254") is True
        assert _is_always_blocked_ip("169.254.0.1") is True

    def test_this_network_blocked(self):
        """0.0.0.0/8 is always blocked."""
        assert _is_always_blocked_ip("0.0.0.0") is True
        assert _is_always_blocked_ip("0.1.2.3") is True

    def test_ipv6_loopback_blocked(self):
        """::1 is always blocked."""
        assert _is_always_blocked_ip("::1") is True

    def test_ipv6_link_local_blocked(self):
        """fe80::/10 is always blocked."""
        assert _is_always_blocked_ip("fe80::1") is True

    def test_public_ip_not_blocked(self):
        """Public IPs are not always-blocked."""
        assert _is_always_blocked_ip("8.8.8.8") is False
        assert _is_always_blocked_ip("93.184.216.34") is False

    def test_private_ip_not_always_blocked(self):
        """RFC 1918 private IPs are NOT in always-blocked (admin can approve)."""
        assert _is_always_blocked_ip("192.168.1.50") is False
        assert _is_always_blocked_ip("10.0.0.1") is False
        assert _is_always_blocked_ip("172.16.0.1") is False

    def test_invalid_string_returns_false(self):
        """Non-IP string returns False."""
        assert _is_always_blocked_ip("not-an-ip") is False
        assert _is_always_blocked_ip("example.com") is False


# =============================================================================
# Admin-Approved Private Access — Integration with Validation Functions
# =============================================================================


class TestAdminApprovedIntegration:
    """Tests for admin_approved parameter in validate_url_with_pinning and
    _validate_hostname_only.
    """

    # --- _validate_hostname_only (proxy mode) with admin_approved ---

    def test_proxy_mode_allows_private_ip_when_admin_approved(self):
        """admin_approved=True allows private IP in proxy mode."""
        url, _ = _validate_hostname_only(
            "http://192.168.1.50:8080/api", {}, admin_approved=True
        )
        assert url == "http://192.168.1.50:8080/api"

    def test_proxy_mode_blocks_private_ip_without_approval(self):
        """admin_approved=False (default) blocks private IP in proxy mode."""
        with pytest.raises(SSRFError, match="blocked IP range"):
            _validate_hostname_only("http://192.168.1.50/api", {})

    def test_proxy_mode_localhost_blocked_even_when_approved(self):
        """Localhost is always blocked even with admin_approved=True."""
        with pytest.raises(SSRFError, match="Blocked hostname"):
            _validate_hostname_only("http://localhost/api", {}, admin_approved=True)

    def test_proxy_mode_metadata_blocked_even_when_approved(self):
        """Cloud metadata endpoints are always blocked."""
        with pytest.raises(SSRFError, match="Blocked"):
            _validate_hostname_only(
                "http://169.254.169.254/latest/meta-data/", {}, admin_approved=True
            )

    def test_proxy_mode_loopback_blocked_even_when_approved(self):
        """Loopback is always blocked even with admin_approved=True."""
        with pytest.raises(SSRFError, match="Blocked"):
            _validate_hostname_only("http://127.0.0.1/api", {}, admin_approved=True)

    def test_proxy_mode_10_x_allowed_when_approved(self):
        """10.x.x.x private IP allowed with admin approval."""
        url, _ = _validate_hostname_only(
            "http://10.0.0.5:9090/api", {}, admin_approved=True
        )
        assert url == "http://10.0.0.5:9090/api"

    # --- validate_url_with_pinning (direct mode) with admin_approved ---

    def test_direct_mode_allows_private_literal_when_approved(self):
        """admin_approved=True allows private IP literal in direct mode."""
        result = validate_url_with_pinning(
            "http://192.168.1.50:8080/api", admin_approved=True
        )
        assert result.pinned_ip == "192.168.1.50"
        assert result.port == 8080

    def test_direct_mode_blocks_private_literal_without_approval(self):
        """Private IP literal is blocked without admin approval."""
        with pytest.raises(SSRFError, match="blocked IP range"):
            validate_url_with_pinning("http://192.168.1.50/api")

    def test_direct_mode_allows_dns_to_private_when_approved(self):
        """Hostname resolving to private IP passes with admin_approved=True."""

        def mock_dns(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("192.168.1.50", port))]

        with patch("socket.getaddrinfo", mock_dns):
            result = validate_url_with_pinning(
                "http://mynas.local:8080/api", admin_approved=True
            )
            assert result.pinned_ip == "192.168.1.50"

    def test_direct_mode_blocks_dns_to_private_without_approval(self):
        """Hostname resolving to private IP is blocked without approval."""

        def mock_dns(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("192.168.1.50", port))]

        with patch("socket.getaddrinfo", mock_dns):
            with pytest.raises(SSRFError, match="resolves to blocked IP"):
                validate_url_with_pinning("http://mynas.local/api")

    def test_direct_mode_loopback_blocked_even_when_approved(self):
        """Loopback is always blocked in direct mode even with approval."""
        with pytest.raises(SSRFError, match="Blocked"):
            validate_url_with_pinning("http://127.0.0.1/api", admin_approved=True)

    def test_direct_mode_metadata_blocked_even_when_approved(self):
        """Metadata IP is always blocked in direct mode even with approval."""

        def mock_dns(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("169.254.169.254", port))]

        with patch("socket.getaddrinfo", mock_dns):
            with pytest.raises(SSRFError, match="resolves to blocked IP"):
                validate_url_with_pinning(
                    "http://evil.example.com/api", admin_approved=True
                )
