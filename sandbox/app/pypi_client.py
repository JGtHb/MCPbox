"""PyPI client - fetches package metadata from PyPI."""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Common module name to PyPI package name mappings
# When the import name differs from the package name
MODULE_TO_PACKAGE: dict[str, str] = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "pyjwt",
    "magic": "python-magic",
    "cv": "opencv-python",
    "skimage": "scikit-image",
    "OpenSSL": "pyopenssl",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "lxml": "lxml",
    "chardet": "chardet",
    "dns": "dnspython",
    "gi": "pygobject",
    "wx": "wxpython",
    "MySQLdb": "mysqlclient",
    "psycopg2": "psycopg2-binary",
    "fitz": "pymupdf",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "xlrd": "xlrd",
    "xlwt": "xlwt",
    "openpyxl": "openpyxl",
}

# PyPI API timeout
PYPI_TIMEOUT = 10.0


@dataclass
class PyPIPackageInfo:
    """Information about a PyPI package."""

    name: str
    version: str
    summary: str | None
    author: str | None
    license: str | None
    home_page: str | None
    requires_python: str | None
    package_url: str


async def get_package_name_for_module(module_name: str) -> str:
    """Get the PyPI package name for a module.

    Args:
        module_name: The import name (e.g., "PIL", "yaml")

    Returns:
        The PyPI package name (e.g., "pillow", "pyyaml")
    """
    # Get top-level module name
    top_level = module_name.split(".")[0]

    # Check if we have a known mapping
    if top_level in MODULE_TO_PACKAGE:
        return MODULE_TO_PACKAGE[top_level]

    # Default: assume package name matches module name
    return top_level


async def fetch_package_info(package_name: str) -> PyPIPackageInfo | None:
    """Fetch package information from PyPI.

    Args:
        package_name: The PyPI package name

    Returns:
        PyPIPackageInfo if found, None otherwise
    """
    url = f"https://pypi.org/pypi/{package_name}/json"

    try:
        async with httpx.AsyncClient(timeout=PYPI_TIMEOUT) as client:
            response = await client.get(url)

            if response.status_code == 404:
                logger.debug(f"Package {package_name} not found on PyPI")
                return None

            response.raise_for_status()
            data = response.json()

            info = data.get("info", {})
            return PyPIPackageInfo(
                name=info.get("name", package_name),
                version=info.get("version", "unknown"),
                summary=info.get("summary"),
                author=info.get("author"),
                license=info.get("license"),
                home_page=info.get("home_page") or info.get("project_url"),
                requires_python=info.get("requires_python"),
                package_url=info.get(
                    "package_url", f"https://pypi.org/project/{package_name}/"
                ),
            )

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching package info for {package_name}")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error fetching package info for {package_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching package info for {package_name}: {e}")
        return None


async def fetch_module_info(module_name: str) -> tuple[str, PyPIPackageInfo | None]:
    """Fetch package information for a module name.

    Handles the module name to package name mapping.

    Args:
        module_name: The import name (e.g., "PIL", "requests")

    Returns:
        Tuple of (package_name, PyPIPackageInfo or None)
    """
    package_name = await get_package_name_for_module(module_name)
    info = await fetch_package_info(package_name)
    return package_name, info


def package_info_to_dict(info: PyPIPackageInfo | None) -> dict[str, Any] | None:
    """Convert PyPIPackageInfo to a dictionary for JSON serialization.

    Args:
        info: The package info or None

    Returns:
        Dictionary or None
    """
    if info is None:
        return None

    return {
        "name": info.name,
        "version": info.version,
        "summary": info.summary,
        "author": info.author,
        "license": info.license,
        "home_page": info.home_page,
        "requires_python": info.requires_python,
        "package_url": info.package_url,
    }
