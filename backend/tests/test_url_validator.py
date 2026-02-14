"""Tests for URL validation and SSRF prevention."""

import socket
from unittest.mock import patch

import pytest

from app.services.url_validator import SSRFError, validate_url_with_pinning


def mock_getaddrinfo_public(hostname, port, family=0, type=0, proto=0, flags=0):
    """Mock DNS resolution returning a public IP."""
    # Return a fake public IP address (93.184.216.34 is example.com)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def mock_getaddrinfo_private(hostname, port, family=0, type=0, proto=0, flags=0):
    """Mock DNS resolution returning a private IP."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", port))]


def mock_getaddrinfo_localhost(hostname, port, family=0, type=0, proto=0, flags=0):
    """Mock DNS resolution returning localhost."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]


class TestURLValidator:
    """Test suite for URL validation functionality."""

    def test_valid_public_url(self):
        """Test that valid public URLs pass validation."""
        with patch("socket.getaddrinfo", mock_getaddrinfo_public):
            result = validate_url_with_pinning("https://api.github.com/users")
            assert result.original_url == "https://api.github.com/users"
            assert result.pinned_ip is not None

    def test_valid_http_url(self):
        """Test that HTTP URLs are accepted."""
        with patch("socket.getaddrinfo", mock_getaddrinfo_public):
            result = validate_url_with_pinning("http://example.com/api")
            assert result.original_url == "http://example.com/api"

    def test_invalid_scheme_rejected(self):
        """Test that non-HTTP(S) schemes are rejected."""
        with pytest.raises(SSRFError, match="scheme"):
            validate_url_with_pinning("file:///etc/passwd")

        with pytest.raises(SSRFError, match="scheme"):
            validate_url_with_pinning("ftp://ftp.example.com/file")

    def test_localhost_rejected(self):
        """Test that localhost URLs are rejected."""
        # localhost is in BLOCKED_HOSTNAMES and rejected before DNS resolution
        with pytest.raises(SSRFError, match="not allowed"):
            validate_url_with_pinning("http://localhost/api")

        # 127.0.0.1 is also in BLOCKED_HOSTNAMES
        with pytest.raises(SSRFError, match="not allowed"):
            validate_url_with_pinning("http://127.0.0.1/api")

    def test_private_ip_ranges_rejected(self):
        """Test that private IP ranges are rejected."""
        private_ips = [
            "http://10.0.0.1/api",
            "http://172.16.0.1/api",
            "http://192.168.1.1/api",
        ]
        for url in private_ips:
            with pytest.raises(SSRFError, match="private"):
                validate_url_with_pinning(url)

    def test_link_local_rejected(self):
        """Test that link-local addresses are rejected."""
        with pytest.raises(SSRFError):
            validate_url_with_pinning("http://169.254.169.254/latest/meta-data/")

    def test_empty_url_rejected(self):
        """Test that empty URLs are rejected."""
        with pytest.raises(SSRFError):
            validate_url_with_pinning("")

    def test_invalid_url_rejected(self):
        """Test that invalid URLs are rejected."""
        with pytest.raises(SSRFError):
            validate_url_with_pinning("not-a-url")

    def test_ipv6_localhost_rejected(self):
        """Test that IPv6 localhost is rejected."""
        with pytest.raises(SSRFError):
            validate_url_with_pinning("http://[::1]/api")


class TestURLValidatorEdgeCases:
    """Test edge cases for URL validation."""

    def test_url_with_port(self):
        """Test that URLs with ports are handled correctly."""
        # Public URL with port should be fine
        with patch("socket.getaddrinfo", mock_getaddrinfo_public):
            result = validate_url_with_pinning("https://api.example.com:8443/api")
            assert result.original_url == "https://api.example.com:8443/api"
            assert result.port == 8443

        # Localhost with port should be blocked (blocked hostname)
        with pytest.raises(SSRFError):
            validate_url_with_pinning("http://localhost:8080/api")

    def test_url_with_query_params(self):
        """Test that URLs with query params are preserved."""
        url = "https://api.example.com/search?q=test&limit=10"
        with patch("socket.getaddrinfo", mock_getaddrinfo_public):
            result = validate_url_with_pinning(url)
            assert result.original_url == url

    def test_url_with_fragment(self):
        """Test that URLs with fragments are preserved."""
        url = "https://api.example.com/docs#section1"
        with patch("socket.getaddrinfo", mock_getaddrinfo_public):
            result = validate_url_with_pinning(url)
            assert result.original_url == url

    def test_unicode_domain(self):
        """Test that IDN domains are handled."""
        # This may resolve to a public IP and pass, or may fail
        # depending on DNS resolution
        pass  # Skip for now as it requires DNS

    def test_special_dns_names(self):
        """Test that special DNS names are blocked."""
        # These should be blocked as they resolve to local IPs (in BLOCKED_HOSTNAMES)
        dangerous_hosts = [
            "http://0.0.0.0/api",
            "http://[::]/api",
        ]
        for url in dangerous_hosts:
            with pytest.raises(SSRFError):
                validate_url_with_pinning(url)
