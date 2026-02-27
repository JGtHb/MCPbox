"""Unit tests for URL validation (SSRF prevention)."""

import ipaddress
from unittest.mock import patch

import pytest

from app.ssrf import (
    SSRFError,
    _is_allowed_private,
    _parse_allowed_private_ranges,
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
# Allowed Private Ranges — Parsing
# =============================================================================


class TestParseAllowedPrivateRanges:
    """Tests for _parse_allowed_private_ranges parser."""

    def test_empty_string(self):
        """Empty string yields no ranges."""
        assert _parse_allowed_private_ranges("") == []

    def test_single_ip(self):
        """Single IP is parsed as /32 network, no port."""
        result = _parse_allowed_private_ranges("192.168.1.50")
        assert len(result) == 1
        network, port = result[0]
        assert network == ipaddress.ip_network("192.168.1.50/32")
        assert port is None

    def test_cidr_range(self):
        """CIDR notation is parsed correctly."""
        result = _parse_allowed_private_ranges("10.0.1.0/24")
        assert len(result) == 1
        network, port = result[0]
        assert network == ipaddress.ip_network("10.0.1.0/24")
        assert port is None

    def test_ip_with_port(self):
        """IP:PORT is parsed with port restriction."""
        result = _parse_allowed_private_ranges("192.168.1.50:8080")
        assert len(result) == 1
        network, port = result[0]
        assert network == ipaddress.ip_network("192.168.1.50/32")
        assert port == 8080

    def test_cidr_with_port(self):
        """CIDR:PORT is parsed correctly."""
        result = _parse_allowed_private_ranges("10.0.1.0/24:443")
        assert len(result) == 1
        network, port = result[0]
        assert network == ipaddress.ip_network("10.0.1.0/24")
        assert port == 443

    def test_multiple_entries(self):
        """Multiple comma-separated entries are all parsed."""
        result = _parse_allowed_private_ranges(
            "192.168.1.50, 10.0.0.0/8:443, 172.16.5.0/24"
        )
        assert len(result) == 3

    def test_whitespace_trimmed(self):
        """Whitespace around entries is trimmed."""
        result = _parse_allowed_private_ranges("  192.168.1.50  ,  10.0.0.1  ")
        assert len(result) == 2

    def test_empty_entries_skipped(self):
        """Empty entries (from trailing commas) are skipped."""
        result = _parse_allowed_private_ranges("192.168.1.50,,10.0.0.1,")
        assert len(result) == 2

    def test_invalid_entry_skipped(self):
        """Invalid entries are silently skipped."""
        result = _parse_allowed_private_ranges("not-an-ip,192.168.1.50")
        assert len(result) == 1
        assert result[0][0] == ipaddress.ip_network("192.168.1.50/32")

    # --- Safety: never-allow ranges ---

    def test_loopback_rejected(self):
        """127.0.0.0/8 range is rejected."""
        assert _parse_allowed_private_ranges("127.0.0.1") == []

    def test_loopback_cidr_rejected(self):
        """Loopback CIDR is rejected."""
        assert _parse_allowed_private_ranges("127.0.0.0/8") == []

    def test_link_local_rejected(self):
        """Link-local / cloud metadata range is rejected."""
        assert _parse_allowed_private_ranges("169.254.169.254") == []

    def test_link_local_cidr_rejected(self):
        """Link-local CIDR is rejected."""
        assert _parse_allowed_private_ranges("169.254.0.0/16") == []

    def test_this_network_rejected(self):
        """0.0.0.0/8 is rejected."""
        assert _parse_allowed_private_ranges("0.0.0.1") == []

    def test_ipv6_loopback_rejected(self):
        """IPv6 loopback is rejected."""
        assert _parse_allowed_private_ranges("::1") == []

    def test_mixed_valid_and_rejected(self):
        """Valid entries pass while unsafe ones are dropped."""
        result = _parse_allowed_private_ranges("192.168.1.50,127.0.0.1,10.0.0.1")
        assert len(result) == 2
        networks = {str(n) for n, _ in result}
        assert "192.168.1.50/32" in networks
        assert "10.0.0.1/32" in networks


# =============================================================================
# Allowed Private Ranges — _is_allowed_private
# =============================================================================


class TestIsAllowedPrivate:
    """Tests for _is_allowed_private helper."""

    def _make_ranges(self, raw):
        """Parse and patch _ALLOWED_PRIVATE_RANGES for testing."""
        return _parse_allowed_private_ranges(raw)

    def test_ip_in_range_allowed(self):
        """IP in an allowed range returns True."""
        ranges = self._make_ranges("192.168.1.0/24")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            assert _is_allowed_private("192.168.1.50") is True

    def test_ip_not_in_range_denied(self):
        """IP outside allowed ranges returns False."""
        ranges = self._make_ranges("192.168.1.0/24")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            assert _is_allowed_private("10.0.0.1") is False

    def test_port_restriction_matching(self):
        """Matching port passes when range has port restriction."""
        ranges = self._make_ranges("192.168.1.50:8080")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            assert _is_allowed_private("192.168.1.50", 8080) is True

    def test_port_restriction_mismatched(self):
        """Non-matching port fails when range has port restriction."""
        ranges = self._make_ranges("192.168.1.50:8080")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            assert _is_allowed_private("192.168.1.50", 443) is False

    def test_no_port_restriction_any_port(self):
        """No port restriction allows any port."""
        ranges = self._make_ranges("192.168.1.50")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            assert _is_allowed_private("192.168.1.50", 8080) is True
            assert _is_allowed_private("192.168.1.50", 443) is True
            assert _is_allowed_private("192.168.1.50") is True

    def test_empty_ranges_always_false(self):
        """No configured ranges always returns False."""
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", []):
            assert _is_allowed_private("192.168.1.50") is False

    def test_invalid_ip_returns_false(self):
        """Non-IP string returns False."""
        ranges = self._make_ranges("192.168.1.0/24")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            assert _is_allowed_private("not-an-ip") is False


# =============================================================================
# Allowed Private Ranges — Integration with Validation Functions
# =============================================================================


class TestAllowedPrivateIntegration:
    """Tests for allowed private ranges in validate_url_with_pinning and
    _validate_hostname_only.
    """

    # --- _validate_hostname_only (proxy mode) ---

    def test_proxy_mode_allows_approved_private_ip(self):
        """Approved private IP passes in proxy mode."""
        ranges = _parse_allowed_private_ranges("192.168.1.50")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            url, _ = _validate_hostname_only("http://192.168.1.50:8080/api", {})
            assert url == "http://192.168.1.50:8080/api"

    def test_proxy_mode_blocks_unapproved_private_ip(self):
        """Non-approved private IP is still blocked in proxy mode."""
        ranges = _parse_allowed_private_ranges("192.168.1.50")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            with pytest.raises(SSRFError, match="blocked IP range"):
                _validate_hostname_only("http://10.0.0.1/api", {})

    def test_proxy_mode_port_restriction_enforced(self):
        """Port restriction blocks mismatched port in proxy mode."""
        ranges = _parse_allowed_private_ranges("192.168.1.50:8080")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            # Port 8080 should pass
            url, _ = _validate_hostname_only("http://192.168.1.50:8080/api", {})
            assert "192.168.1.50" in url

            # Port 443 (default HTTPS) should be blocked
            with pytest.raises(SSRFError, match="blocked IP range"):
                _validate_hostname_only("https://192.168.1.50/api", {})

    def test_proxy_mode_localhost_still_blocked(self):
        """Localhost is always blocked even with allowed private ranges."""
        ranges = _parse_allowed_private_ranges("192.168.1.0/24")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            with pytest.raises(SSRFError, match="Blocked hostname"):
                _validate_hostname_only("http://localhost/api", {})

    def test_proxy_mode_metadata_still_blocked(self):
        """Metadata endpoints are always blocked (169.254/16 rejected by parser)."""
        ranges = _parse_allowed_private_ranges("169.254.169.254")
        assert len(ranges) == 0  # Parser rejects link-local
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            with pytest.raises(SSRFError, match="Blocked"):
                _validate_hostname_only("http://169.254.169.254/latest/meta-data/", {})

    # --- validate_url_with_pinning (direct mode) ---

    def test_direct_mode_allows_approved_private_literal_ip(self):
        """Approved private IP literal passes in direct mode."""
        ranges = _parse_allowed_private_ranges("192.168.1.50")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            result = validate_url_with_pinning("http://192.168.1.50:8080/api")
            assert result.pinned_ip == "192.168.1.50"
            assert result.port == 8080

    def test_direct_mode_blocks_unapproved_private_literal_ip(self):
        """Non-approved private IP literal is blocked in direct mode."""
        ranges = _parse_allowed_private_ranges("192.168.1.50")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            with pytest.raises(SSRFError, match="blocked IP range"):
                validate_url_with_pinning("http://10.0.0.1/api")

    def test_direct_mode_allows_dns_resolving_to_approved_private(self):
        """Hostname resolving to approved private IP passes in direct mode."""
        ranges = _parse_allowed_private_ranges("192.168.1.50")

        def mock_dns(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("192.168.1.50", port))]

        with (
            patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges),
            patch("socket.getaddrinfo", mock_dns),
        ):
            result = validate_url_with_pinning("http://mynas.local:8080/api")
            assert result.pinned_ip == "192.168.1.50"

    def test_direct_mode_blocks_dns_resolving_to_unapproved_private(self):
        """Hostname resolving to non-approved private IP is blocked."""
        ranges = _parse_allowed_private_ranges("192.168.1.50")

        def mock_dns(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("10.0.0.5", port))]

        with (
            patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges),
            patch("socket.getaddrinfo", mock_dns),
        ):
            with pytest.raises(SSRFError, match="resolves to blocked IP"):
                validate_url_with_pinning("http://other.local/api")

    def test_direct_mode_port_restriction_on_literal_ip(self):
        """Port restriction enforced for literal IP in direct mode."""
        ranges = _parse_allowed_private_ranges("192.168.1.50:8080")
        with patch("app.ssrf._ALLOWED_PRIVATE_RANGES", ranges):
            # Matching port passes
            result = validate_url_with_pinning("http://192.168.1.50:8080/api")
            assert result.pinned_ip == "192.168.1.50"

            # Default HTTP port (80) is blocked
            with pytest.raises(SSRFError, match="blocked IP range"):
                validate_url_with_pinning("http://192.168.1.50/api")
