"""Tests for OSV.dev and deps.dev safety clients."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from app.osv_client import (
    fetch_vulnerabilities,
    VulnerabilityInfo,
    _extract_severity,
    _extract_fixed_version,
    _cache as osv_cache,
)
from app.deps_client import (
    fetch_deps_info,
    DepsDevInfo,
    _cache as deps_cache,
)


# =============================================================================
# OSV Client Tests
# =============================================================================


class TestOSVClient:
    """Tests for OSV.dev vulnerability fetching."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear caches before each test."""
        osv_cache.clear()
        yield
        osv_cache.clear()

    @pytest.mark.asyncio
    async def test_fetch_vulnerabilities_found(self):
        """Test fetching vulnerabilities that exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "vulns": [
                {
                    "id": "GHSA-1234-abcd-5678",
                    "summary": "SQL injection vulnerability",
                    "database_specific": {"severity": "HIGH"},
                    "affected": [
                        {
                            "package": {"name": "example-pkg", "ecosystem": "PyPI"},
                            "ranges": [
                                {
                                    "events": [
                                        {"introduced": "0"},
                                        {"fixed": "2.0.1"},
                                    ]
                                }
                            ],
                        }
                    ],
                    "references": [
                        {
                            "type": "ADVISORY",
                            "url": "https://github.com/advisories/GHSA-1234",
                        }
                    ],
                }
            ]
        }

        with patch("app.osv_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            results = await fetch_vulnerabilities("example-pkg")

        assert len(results) == 1
        assert results[0].id == "GHSA-1234-abcd-5678"
        assert results[0].summary == "SQL injection vulnerability"
        assert results[0].severity == "HIGH"
        assert results[0].fixed_version == "2.0.1"
        assert results[0].link == "https://github.com/advisories/GHSA-1234"

    @pytest.mark.asyncio
    async def test_fetch_vulnerabilities_none_found(self):
        """Test when no vulnerabilities exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {}

        with patch("app.osv_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            results = await fetch_vulnerabilities("safe-package")

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_vulnerabilities_timeout(self):
        """Test graceful handling of timeout."""
        with patch("app.osv_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            results = await fetch_vulnerabilities("slow-package")

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_vulnerabilities_http_error(self):
        """Test graceful handling of HTTP errors."""
        with patch("app.osv_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error", request=MagicMock(), response=mock_response
            )
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            results = await fetch_vulnerabilities("error-package")

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_vulnerabilities_caching(self):
        """Test that results are cached."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"vulns": []}

        with patch("app.osv_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            # First call hits API
            await fetch_vulnerabilities("cached-pkg")
            # Second call uses cache
            await fetch_vulnerabilities("cached-pkg")

        # Should only have been called once
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_vulnerabilities_deduplicates(self):
        """Test that duplicate vuln IDs are deduplicated."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "vulns": [
                {"id": "CVE-2024-001", "summary": "First"},
                {"id": "CVE-2024-001", "summary": "Duplicate"},
                {"id": "CVE-2024-002", "summary": "Second"},
            ]
        }

        with patch("app.osv_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            results = await fetch_vulnerabilities("dup-pkg")

        assert len(results) == 2
        assert results[0].id == "CVE-2024-001"
        assert results[1].id == "CVE-2024-002"

    def test_extract_severity_from_database_specific(self):
        """Test severity extraction from database_specific field."""
        vuln = {"database_specific": {"severity": "CRITICAL"}}
        assert _extract_severity(vuln) == "CRITICAL"

    def test_extract_severity_from_ecosystem_specific(self):
        """Test severity extraction from ecosystem_specific field."""
        vuln = {"affected": [{"ecosystem_specific": {"severity": "medium"}}]}
        assert _extract_severity(vuln) == "MEDIUM"

    def test_extract_severity_none(self):
        """Test severity extraction when no severity data exists."""
        vuln = {}
        assert _extract_severity(vuln) is None

    def test_extract_fixed_version(self):
        """Test fixed version extraction."""
        vuln = {
            "affected": [
                {
                    "package": {"name": "requests", "ecosystem": "PyPI"},
                    "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.31.0"}]}],
                }
            ]
        }
        assert _extract_fixed_version(vuln, "requests") == "2.31.0"

    def test_extract_fixed_version_no_fix(self):
        """Test fixed version when no fix exists."""
        vuln = {
            "affected": [
                {
                    "package": {"name": "requests", "ecosystem": "PyPI"},
                    "ranges": [{"events": [{"introduced": "0"}]}],
                }
            ]
        }
        assert _extract_fixed_version(vuln, "requests") is None

    def test_vulnerability_info_to_dict(self):
        """Test VulnerabilityInfo serialization."""
        vuln = VulnerabilityInfo(
            id="CVE-2024-001",
            summary="Test vulnerability",
            severity="HIGH",
            fixed_version="1.0.1",
            link="https://example.com",
        )
        d = vuln.to_dict()
        assert d["id"] == "CVE-2024-001"
        assert d["severity"] == "HIGH"
        assert d["fixed_version"] == "1.0.1"


# =============================================================================
# deps.dev Client Tests
# =============================================================================


class TestDepsClient:
    """Tests for deps.dev project health fetching."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear caches before each test."""
        deps_cache.clear()
        yield
        deps_cache.clear()

    @pytest.mark.asyncio
    async def test_fetch_deps_info_success(self):
        """Test successful deps.dev fetch with scorecard."""
        pkg_response = MagicMock()
        pkg_response.status_code = 200
        pkg_response.json.return_value = {
            "versions": [{"versionKey": {"version": "2.31.0"}, "isDefault": True}]
        }

        version_response = MagicMock()
        version_response.status_code = 200
        version_response.json.return_value = {
            "dependencies": [{"name": "dep1"}, {"name": "dep2"}, {"name": "dep3"}],
            "links": [
                {"label": "SOURCE_REPO", "url": "https://github.com/psf/requests"}
            ],
        }

        scorecard_response = MagicMock()
        scorecard_response.status_code = 200
        scorecard_response.json.return_value = {
            "scorecard": {"overallScore": 7.5, "date": "2024-01-15"}
        }

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "/versions/" in url:
                return version_response
            elif "/projects/" in url:
                return scorecard_response
            else:
                return pkg_response

        with patch("app.deps_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = mock_get
            mock_client_cls.return_value = mock_client

            result = await fetch_deps_info("requests")

        assert result is not None
        assert result.dependency_count == 3
        assert result.scorecard_score == 7.5
        assert result.source_repo == "github.com/psf/requests"

    @pytest.mark.asyncio
    async def test_fetch_deps_info_no_scorecard(self):
        """Test deps.dev fetch when no scorecard is available."""
        pkg_response = MagicMock()
        pkg_response.status_code = 200
        pkg_response.json.return_value = {
            "versions": [{"versionKey": {"version": "1.0.0"}, "isDefault": True}]
        }

        version_response = MagicMock()
        version_response.status_code = 200
        version_response.json.return_value = {
            "dependencies": [],
            "links": [],
        }

        async def mock_get(url, **kwargs):
            if "/versions/" in url:
                return version_response
            else:
                return pkg_response

        with patch("app.deps_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = mock_get
            mock_client_cls.return_value = mock_client

            result = await fetch_deps_info("small-pkg")

        assert result is not None
        assert result.dependency_count == 0
        assert result.scorecard_score is None
        assert result.source_repo is None

    @pytest.mark.asyncio
    async def test_fetch_deps_info_package_not_found(self):
        """Test deps.dev when package doesn't exist."""
        pkg_response = MagicMock()
        pkg_response.status_code = 404

        async def mock_get(url, **kwargs):
            return pkg_response

        with patch("app.deps_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = mock_get
            mock_client_cls.return_value = mock_client

            result = await fetch_deps_info("nonexistent-pkg")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_deps_info_timeout(self):
        """Test graceful handling of timeout."""
        with patch("app.deps_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            result = await fetch_deps_info("slow-pkg")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_deps_info_caching(self):
        """Test that results are cached."""
        pkg_response = MagicMock()
        pkg_response.status_code = 200
        pkg_response.json.return_value = {
            "versions": [{"versionKey": {"version": "1.0.0"}, "isDefault": True}]
        }
        version_response = MagicMock()
        version_response.status_code = 200
        version_response.json.return_value = {"dependencies": [], "links": []}

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "/versions/" in url:
                return version_response
            return pkg_response

        with patch("app.deps_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = mock_get
            mock_client_cls.return_value = mock_client

            await fetch_deps_info("cached-pkg")
            await fetch_deps_info("cached-pkg")

        # Should only have made API calls once (2 calls: package + version)
        assert call_count == 2

    def test_deps_dev_info_to_dict(self):
        """Test DepsDevInfo serialization."""
        info = DepsDevInfo(
            dependency_count=5,
            scorecard_score=8.2,
            scorecard_date="2024-01-15",
            source_repo="github.com/owner/repo",
        )
        d = info.to_dict()
        assert d["dependency_count"] == 5
        assert d["scorecard_score"] == 8.2
        assert d["source_repo"] == "github.com/owner/repo"
