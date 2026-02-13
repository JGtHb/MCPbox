"""Tests for request utility functions."""

import pytest
from unittest.mock import MagicMock

from app.core.request_utils import _is_valid_ip, get_client_ip


class TestIsValidIP:
    """Tests for _is_valid_ip function."""

    def test_valid_ipv4_addresses(self):
        """Test valid IPv4 addresses."""
        assert _is_valid_ip("192.168.1.1") is True
        assert _is_valid_ip("10.0.0.1") is True
        assert _is_valid_ip("172.16.0.1") is True
        assert _is_valid_ip("8.8.8.8") is True
        assert _is_valid_ip("255.255.255.255") is True
        assert _is_valid_ip("0.0.0.0") is True

    def test_valid_ipv6_addresses(self):
        """Test valid IPv6 addresses."""
        assert _is_valid_ip("::1") is True
        assert _is_valid_ip("fe80::1") is True
        assert _is_valid_ip("2001:db8::1") is True
        assert _is_valid_ip("::ffff:192.168.1.1") is True
        assert _is_valid_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334") is True

    def test_invalid_ip_addresses(self):
        """Test invalid IP addresses."""
        assert _is_valid_ip("") is False
        assert _is_valid_ip("not-an-ip") is False
        assert _is_valid_ip("256.1.1.1") is False
        assert _is_valid_ip("192.168.1") is False
        assert _is_valid_ip("192.168.1.1.1") is False
        assert _is_valid_ip("example.com") is False
        assert _is_valid_ip("192.168.1.1:8080") is False
        assert _is_valid_ip("192.168.1.1/24") is False

    def test_edge_cases(self):
        """Test edge cases."""
        assert _is_valid_ip("   ") is False
        assert _is_valid_ip("192.168.1.1 ") is False  # Trailing space
        assert _is_valid_ip(" 192.168.1.1") is False  # Leading space


class TestGetClientIP:
    """Tests for get_client_ip function."""

    def _create_mock_request(
        self,
        cf_connecting_ip=None,
        x_real_ip=None,
        x_forwarded_for=None,
        client_host=None,
    ):
        """Create a mock FastAPI request."""
        request = MagicMock()

        headers = {}
        if cf_connecting_ip:
            headers["CF-Connecting-IP"] = cf_connecting_ip
        if x_real_ip:
            headers["X-Real-IP"] = x_real_ip
        if x_forwarded_for:
            headers["X-Forwarded-For"] = x_forwarded_for

        request.headers.get = lambda key, default=None: headers.get(key, default)

        if client_host:
            request.client = MagicMock()
            request.client.host = client_host
        else:
            request.client = None

        return request

    def test_cf_connecting_ip_priority(self):
        """Test that CF-Connecting-IP has highest priority."""
        request = self._create_mock_request(
            cf_connecting_ip="1.2.3.4",
            x_real_ip="5.6.7.8",
            client_host="9.10.11.12",
        )

        result = get_client_ip(request)
        assert result == "1.2.3.4"

    def test_x_real_ip_from_localhost(self):
        """Test that X-Real-IP is used when request comes from localhost."""
        # X-Real-IP is only trusted when request comes from localhost (trusted proxy)
        request = self._create_mock_request(
            x_real_ip="5.6.7.8",
            client_host="127.0.0.1",  # Must be localhost to trust X-Real-IP
        )

        result = get_client_ip(request)
        assert result == "5.6.7.8"

    def test_x_real_ip_not_trusted_from_external(self):
        """Test that X-Real-IP is NOT trusted from external sources (security)."""
        # When client is not localhost, X-Real-IP should be ignored to prevent spoofing
        request = self._create_mock_request(
            x_real_ip="5.6.7.8",
            client_host="9.10.11.12",  # External client
        )

        # Should use client.host, not X-Real-IP
        result = get_client_ip(request)
        assert result == "9.10.11.12"

    def test_client_host_fallback(self):
        """Test fallback to client.host."""
        request = self._create_mock_request(client_host="127.0.0.1")

        result = get_client_ip(request)
        assert result == "127.0.0.1"

    def test_no_ip_available(self):
        """Test when no IP is available."""
        request = self._create_mock_request()

        result = get_client_ip(request)
        assert result is None

    def test_x_forwarded_for_ignored(self):
        """Test that X-Forwarded-For is NOT used (security)."""
        request = self._create_mock_request(
            x_forwarded_for="1.2.3.4, 5.6.7.8",
            client_host="9.10.11.12",
        )

        # Should use client.host, not X-Forwarded-For
        result = get_client_ip(request)
        assert result == "9.10.11.12"

    def test_invalid_cf_connecting_ip_skipped(self):
        """Test that invalid CF-Connecting-IP is skipped."""
        request = self._create_mock_request(
            cf_connecting_ip="not-an-ip",
            x_real_ip="5.6.7.8",
            client_host="127.0.0.1",  # Localhost to trust X-Real-IP
        )

        result = get_client_ip(request)
        assert result == "5.6.7.8"

    def test_invalid_x_real_ip_skipped(self):
        """Test that invalid X-Real-IP is skipped."""
        request = self._create_mock_request(
            x_real_ip="invalid",
            client_host="192.168.1.1",
        )

        result = get_client_ip(request)
        assert result == "192.168.1.1"

    def test_whitespace_trimmed_from_headers(self):
        """Test that whitespace is trimmed from header values."""
        request = self._create_mock_request(
            cf_connecting_ip="  1.2.3.4  ",
        )

        result = get_client_ip(request)
        assert result == "1.2.3.4"

    def test_ipv6_cf_connecting_ip(self):
        """Test IPv6 address in CF-Connecting-IP."""
        request = self._create_mock_request(
            cf_connecting_ip="2001:db8::1",
        )

        result = get_client_ip(request)
        assert result == "2001:db8::1"

    def test_ipv6_x_real_ip(self):
        """Test IPv6 address in X-Real-IP from localhost."""
        request = self._create_mock_request(
            x_real_ip="2001:db8::1",
            client_host="127.0.0.1",  # Localhost to trust X-Real-IP
        )

        result = get_client_ip(request)
        assert result == "2001:db8::1"

    def test_empty_header_values(self):
        """Test empty header values are handled."""
        request = self._create_mock_request(
            cf_connecting_ip="",
            x_real_ip="",
            client_host="192.168.1.1",
        )

        # Empty strings should be skipped, fall through to client.host
        result = get_client_ip(request)
        assert result == "192.168.1.1"


class TestGetClientIPLogging:
    """Tests for get_client_ip logging behavior."""

    def test_invalid_cf_ip_logs_warning(self):
        """Test that invalid CF-Connecting-IP logs a warning."""
        from unittest.mock import patch

        request = MagicMock()
        request.headers.get = lambda key, default=None: (
            "invalid-ip" if key == "CF-Connecting-IP" else None
        )
        request.client = None

        with patch("app.core.request_utils.logger") as mock_logger:
            get_client_ip(request)
            mock_logger.warning.assert_called()
            assert "Invalid CF-Connecting-IP" in str(mock_logger.warning.call_args)

    def test_invalid_x_real_ip_logs_warning(self):
        """Test that invalid X-Real-IP logs a warning when from localhost."""
        from unittest.mock import patch

        request = MagicMock()
        request.headers.get = lambda key, default=None: "invalid-ip" if key == "X-Real-IP" else None
        # Must be localhost for X-Real-IP to be checked at all
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        with patch("app.core.request_utils.logger") as mock_logger:
            get_client_ip(request)
            mock_logger.warning.assert_called()
            assert "Invalid X-Real-IP" in str(mock_logger.warning.call_args)
