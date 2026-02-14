"""deps.dev client — fetches dependency count and OpenSSF Scorecard data.

Uses Google's deps.dev API (https://deps.dev/) for project health metrics.
Free API, no key required.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

DEPS_API_BASE = "https://api.deps.dev/v3alpha"
DEPS_TIMEOUT = 10.0

# In-memory cache: package_name -> (timestamp, result)
_cache: dict[str, tuple[float, "DepsDevInfo | None"]] = {}
_CACHE_TTL = 3600  # 1 hour


@dataclass
class DepsDevInfo:
    """Dependency and project health information from deps.dev."""

    dependency_count: int | None
    scorecard_score: float | None  # OpenSSF Scorecard overall score (0-10)
    scorecard_date: str | None  # Date of last scorecard evaluation
    source_repo: str | None  # e.g., "github.com/psf/requests"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_count": self.dependency_count,
            "scorecard_score": self.scorecard_score,
            "scorecard_date": self.scorecard_date,
            "source_repo": self.source_repo,
        }


async def _fetch_version_info(
    client: httpx.AsyncClient, package_name: str, version: str
) -> tuple[int | None, str | None]:
    """Fetch dependency count and source repo for a specific version.

    Returns:
        Tuple of (dependency_count, source_repo_url)
    """
    url = f"{DEPS_API_BASE}/systems/pypi/packages/{quote(package_name, safe='')}/versions/{quote(version, safe='')}"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None, None
        data = resp.json()

        dep_count = len(data.get("dependencies", []))

        source_repo = None
        for link in data.get("links", []):
            if link.get("label") == "SOURCE_REPO":
                url_val = link.get("url", "")
                # Extract github.com/owner/repo from URL
                if "github.com/" in url_val:
                    parts = url_val.rstrip("/").split("github.com/")
                    if len(parts) == 2:
                        repo_path = parts[1].split("#")[0].split("?")[0]
                        # Only keep owner/repo (no subpaths)
                        segments = repo_path.strip("/").split("/")
                        if len(segments) >= 2:
                            source_repo = f"github.com/{segments[0]}/{segments[1]}"
                break

        return dep_count, source_repo
    except Exception as e:
        logger.debug(
            "Failed to fetch version info for %s@%s: %s", package_name, version, e
        )
        return None, None


async def _fetch_scorecard(
    client: httpx.AsyncClient, source_repo: str
) -> tuple[float | None, str | None]:
    """Fetch OpenSSF Scorecard for a GitHub project.

    Args:
        source_repo: e.g., "github.com/psf/requests"

    Returns:
        Tuple of (overall_score, evaluation_date)
    """
    url = f"{DEPS_API_BASE}/projects/{quote(source_repo, safe='')}"
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None, None
        data = resp.json()

        scorecard = data.get("scorecard")
        if scorecard:
            return scorecard.get("overallScore"), scorecard.get("date")

        return None, None
    except Exception as e:
        logger.debug("Failed to fetch scorecard for %s: %s", source_repo, e)
        return None, None


async def fetch_deps_info(
    package_name: str, version: str | None = None
) -> DepsDevInfo | None:
    """Fetch dependency and project health info from deps.dev.

    Args:
        package_name: The PyPI package name
        version: Specific version to check (uses default/latest if None)

    Returns:
        DepsDevInfo or None on error
    """
    cache_key = f"{package_name}@{version or 'default'}"

    # Check cache
    now = time.monotonic()
    if cache_key in _cache:
        cached_time, cached_result = _cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_result

    try:
        async with httpx.AsyncClient(timeout=DEPS_TIMEOUT) as client:
            # If no version specified, get the default version from package info
            if not version:
                pkg_url = f"{DEPS_API_BASE}/systems/pypi/packages/{quote(package_name, safe='')}"
                resp = await client.get(pkg_url)
                if resp.status_code != 200:
                    _cache[cache_key] = (now, None)
                    return None
                pkg_data = resp.json()

                # Find the default version
                for v in pkg_data.get("versions", []):
                    if v.get("isDefault"):
                        version = v.get("versionKey", {}).get("version")
                        break

                if not version:
                    # Fall back to latest version in the list
                    versions = pkg_data.get("versions", [])
                    if versions:
                        version = versions[-1].get("versionKey", {}).get("version")

                if not version:
                    _cache[cache_key] = (now, None)
                    return None

            # Get version details (dependencies + source repo)
            dep_count, source_repo = await _fetch_version_info(
                client, package_name, version
            )

            # Get scorecard if we found a GitHub repo
            scorecard_score = None
            scorecard_date = None
            if source_repo:
                scorecard_score, scorecard_date = await _fetch_scorecard(
                    client, source_repo
                )

            result = DepsDevInfo(
                dependency_count=dep_count,
                scorecard_score=scorecard_score,
                scorecard_date=scorecard_date,
                source_repo=source_repo,
            )

            _cache[cache_key] = (now, result)
            return result

    except httpx.TimeoutException:
        logger.warning("Timeout fetching deps.dev info for %s", package_name)
        _cache[cache_key] = (now, None)
        return None
    except Exception as e:
        logger.warning("Error fetching deps.dev info for %s: %s", package_name, e)
        _cache[cache_key] = (now, None)
        return None
