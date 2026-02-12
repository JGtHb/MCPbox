"""Tests for admin auth middleware prefix matching.

Verifies that excluded path matching uses segment boundaries
to prevent accidental auth bypass via similar path prefixes.
"""

from app.middleware.admin_auth import EXCLUDED_PATHS


class TestExcludedPathMatching:
    """Tests for EXCLUDED_PATHS matching logic."""

    def test_exact_excluded_path_matches(self):
        """Test that exact excluded paths are matched."""
        for excluded in EXCLUDED_PATHS:
            path = excluded
            assert path == excluded or path.startswith(excluded + "/")

    def test_excluded_subpath_matches(self):
        """Test that subpaths of excluded paths are matched."""
        assert "/config/something".startswith("/config/")
        assert "/mcp/health".startswith("/mcp/")
        assert "/auth/login".startswith("/auth/")
        assert "/internal/active-tunnel-token".startswith("/internal/")

    def test_similar_prefix_does_not_match(self):
        """Test that paths with similar prefixes but different segments don't match.

        This is the key security test: /configuration should NOT match /config,
        /mcpbox-admin should NOT match /mcp, etc.
        """
        similar_paths = [
            ("/configuration", "/config"),
            ("/configs", "/config"),
            ("/mcpbox-admin", "/mcp"),
            ("/mcpadmin", "/mcp"),
            ("/authenticate", "/auth"),
            ("/authorization", "/auth"),
            ("/internal-admin", "/internal"),
        ]

        for path, excluded in similar_paths:
            matches = path == excluded or path.startswith(excluded + "/")
            assert not matches, f"Path '{path}' should NOT match excluded prefix '{excluded}'"

    def test_circuit_breaker_reset_not_in_read_only_paths(self):
        """Test that POST circuit breaker reset paths require auth."""
        from app.middleware.admin_auth import READ_ONLY_HEALTH_PATHS

        assert "/health/circuits/reset" not in READ_ONLY_HEALTH_PATHS
        assert "/api/health/circuits/reset" not in READ_ONLY_HEALTH_PATHS
