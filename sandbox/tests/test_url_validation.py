"""Unit tests for URL validation (SSRF prevention)."""

from unittest.mock import patch

import pytest

from app.ssrf import SSRFError, validate_url_with_pinning


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
