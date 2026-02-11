"""Package sync - synchronizes packages with backend on startup."""

import asyncio
import logging
import os

import httpx

from app.package_installer import install_packages, InstallStatus
from app.stdlib_detector import classify_modules

logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
SYNC_RETRY_DELAY = 5  # seconds between retries
SYNC_MAX_RETRIES = 12  # 12 retries * 5 seconds = 1 minute max wait
SYNC_TIMEOUT = 10.0  # HTTP timeout for backend requests


async def fetch_modules_from_backend() -> list[str] | None:
    """Fetch the allowed modules list from the backend.

    Returns:
        List of module names, or None if fetch failed
    """
    url = f"{BACKEND_URL}/api/settings/modules"

    try:
        async with httpx.AsyncClient(timeout=SYNC_TIMEOUT) as client:
            response = await client.get(url)

            if response.status_code != 200:
                logger.warning(
                    f"Backend returned status {response.status_code} for modules fetch"
                )
                return None

            data = response.json()
            return data.get("allowed_modules", [])

    except httpx.ConnectError:
        logger.debug(f"Backend not reachable at {url}")
        return None
    except httpx.TimeoutException:
        logger.warning("Timeout fetching modules from backend")
        return None
    except Exception as e:
        logger.error(f"Error fetching modules from backend: {e}")
        return None


async def sync_packages_with_backend() -> dict:
    """Sync packages with the backend's module list.

    Fetches the allowed modules from backend and installs any
    missing third-party packages.

    Returns:
        Dict with sync results
    """
    logger.info("Starting package sync with backend...")

    # Fetch modules from backend with retries
    modules = None
    for attempt in range(1, SYNC_MAX_RETRIES + 1):
        modules = await fetch_modules_from_backend()
        if modules is not None:
            break

        if attempt < SYNC_MAX_RETRIES:
            logger.info(
                f"Backend not ready, retrying in {SYNC_RETRY_DELAY}s "
                f"(attempt {attempt}/{SYNC_MAX_RETRIES})"
            )
            await asyncio.sleep(SYNC_RETRY_DELAY)

    if modules is None:
        logger.warning(
            "Could not fetch modules from backend after all retries. "
            "Packages will be installed on-demand."
        )
        return {
            "success": False,
            "error": "Backend not reachable",
            "installed": 0,
            "failed": 0,
            "stdlib": 0,
        }

    logger.info(f"Fetched {len(modules)} modules from backend")

    # Classify modules
    classification = classify_modules(modules)
    third_party = classification["third_party"]
    stdlib_count = len(classification["stdlib"])

    if not third_party:
        logger.info(f"All {stdlib_count} modules are stdlib, no packages to install")
        return {
            "success": True,
            "installed": 0,
            "failed": 0,
            "stdlib": stdlib_count,
        }

    logger.info(
        f"Found {len(third_party)} third-party packages to check/install: "
        f"{', '.join(third_party[:10])}{'...' if len(third_party) > 10 else ''}"
    )

    # Install third-party packages
    results = await install_packages(third_party)

    installed = sum(1 for r in results if r.status == InstallStatus.INSTALLED)
    failed = sum(1 for r in results if r.status == InstallStatus.FAILED)

    # Log any failures
    for result in results:
        if result.status == InstallStatus.FAILED:
            logger.error(
                f"Failed to install {result.package_name}: {result.error_message}"
            )

    logger.info(
        f"Package sync complete: {installed} installed, "
        f"{failed} failed, {stdlib_count} stdlib"
    )

    return {
        "success": failed == 0,
        "installed": installed,
        "failed": failed,
        "stdlib": stdlib_count,
    }


async def startup_sync():
    """Background task for package sync on startup.

    Called from main.py's lifespan context manager.
    """
    # Small delay to let the service start up
    await asyncio.sleep(2)

    try:
        result = await sync_packages_with_backend()
        if not result["success"]:
            if result.get("error"):
                logger.warning(f"Startup sync incomplete: {result['error']}")
            elif result["failed"] > 0:
                logger.warning(
                    f"Startup sync completed with {result['failed']} failures"
                )
    except Exception as e:
        logger.error(f"Error during startup package sync: {e}")
