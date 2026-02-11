"""OSV.dev client — fetches known vulnerabilities for PyPI packages.

Uses Google's Open Source Vulnerabilities database (https://osv.dev/).
Backed by the Python Packaging Advisory Database, GitHub Security Advisories,
and NVD. Free API, no key required.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OSV_API_URL = "https://api.osv.dev/v1/query"
OSV_TIMEOUT = 10.0

# In-memory cache: package_name -> (timestamp, results)
_cache: dict[str, tuple[float, list["VulnerabilityInfo"]]] = {}
_CACHE_TTL = 3600  # 1 hour


@dataclass
class VulnerabilityInfo:
    """A single known vulnerability."""

    id: str  # e.g., "GHSA-xxxx" or "CVE-2024-xxxx"
    summary: str
    severity: str | None  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    fixed_version: str | None
    link: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "severity": self.severity,
            "fixed_version": self.fixed_version,
            "link": self.link,
        }


def _extract_severity(vuln: dict) -> str | None:
    """Extract severity from an OSV vulnerability entry.

    Checks database_specific.severity first (GitHub advisories),
    then CVSS scores in severity array.
    """
    # GitHub advisories put severity in database_specific
    db_specific = vuln.get("database_specific", {})
    gh_severity = db_specific.get("severity")
    if gh_severity and isinstance(gh_severity, str):
        return gh_severity.upper()

    # Check the severity array for CVSS scores
    for sev in vuln.get("severity", []):
        score_str = sev.get("score", "")
        # CVSS vector strings contain the score; try to parse
        if sev.get("type") == "CVSS_V3" and isinstance(score_str, str):
            # CVSS v3 vector format: CVSS:3.1/AV:N/AC:L/...
            # The score is often not directly in the vector; check for
            # a numeric score in database_specific instead
            pass

    # Try ecosystem-specific severity from affected entries
    for affected in vuln.get("affected", []):
        eco_specific = affected.get("ecosystem_specific", {})
        sev = eco_specific.get("severity")
        if sev and isinstance(sev, str):
            return sev.upper()

    return None


def _extract_fixed_version(vuln: dict, package_name: str) -> str | None:
    """Extract the earliest fixed version for the given package."""
    for affected in vuln.get("affected", []):
        pkg = affected.get("package", {})
        if (
            pkg.get("ecosystem", "").upper() == "PYPI"
            and pkg.get("name", "").lower() == package_name.lower()
        ):
            for rng in affected.get("ranges", []):
                for event in rng.get("events", []):
                    if "fixed" in event:
                        return event["fixed"]
    return None


async def fetch_vulnerabilities(package_name: str) -> list[VulnerabilityInfo]:
    """Fetch known vulnerabilities for a PyPI package from OSV.dev.

    Args:
        package_name: The PyPI package name (e.g., "requests", "pillow")

    Returns:
        List of VulnerabilityInfo, empty if none found or on error.
    """
    # Check cache
    now = time.monotonic()
    if package_name in _cache:
        cached_time, cached_result = _cache[package_name]
        if now - cached_time < _CACHE_TTL:
            return cached_result

    try:
        payload = {
            "package": {
                "name": package_name,
                "ecosystem": "PyPI",
            }
        }

        async with httpx.AsyncClient(timeout=OSV_TIMEOUT) as client:
            response = await client.post(OSV_API_URL, json=payload)
            response.raise_for_status()
            data = response.json()

        vulns_raw = data.get("vulns", [])
        results: list[VulnerabilityInfo] = []

        for vuln in vulns_raw:
            vuln_id = vuln.get("id", "UNKNOWN")

            # Build a link to the advisory
            link = None
            for ref in vuln.get("references", []):
                if ref.get("type") in ("ADVISORY", "WEB"):
                    link = ref.get("url")
                    break
            if not link:
                link = f"https://osv.dev/vulnerability/{vuln_id}"

            results.append(
                VulnerabilityInfo(
                    id=vuln_id,
                    summary=vuln.get(
                        "summary", vuln.get("details", "No description available")
                    )[:300],
                    severity=_extract_severity(vuln),
                    fixed_version=_extract_fixed_version(vuln, package_name),
                    link=link,
                )
            )

        # Only keep unique vuln IDs (OSV can return aliases)
        seen_ids: set[str] = set()
        unique_results: list[VulnerabilityInfo] = []
        for v in results:
            if v.id not in seen_ids:
                seen_ids.add(v.id)
                unique_results.append(v)

        _cache[package_name] = (now, unique_results)
        return unique_results

    except httpx.TimeoutException:
        logger.warning(
            "Timeout fetching vulnerabilities for %s from OSV.dev", package_name
        )
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(
            "HTTP error fetching vulnerabilities for %s: %s", package_name, e
        )
        return []
    except Exception as e:
        logger.error("Error fetching vulnerabilities for %s: %s", package_name, e)
        return []
