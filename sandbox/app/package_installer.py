"""Package installer - installs Python packages to custom directory."""

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from enum import Enum

from app.pypi_client import get_package_name_for_module
from app.stdlib_detector import is_stdlib_module

logger = logging.getLogger(__name__)

# Default packages directory (can be overridden via environment)
DEFAULT_PACKAGES_DIR = "/app/site-packages"


class InstallStatus(str, Enum):
    """Package installation status."""

    NOT_REQUIRED = "not_required"  # stdlib module, no install needed
    PENDING = "pending"  # queued for installation
    INSTALLING = "installing"  # currently installing
    INSTALLED = "installed"  # successfully installed
    FAILED = "failed"  # installation failed


@dataclass
class InstallResult:
    """Result of a package installation attempt."""

    module_name: str
    package_name: str
    status: InstallStatus
    version: str | None = None
    error_message: str | None = None


def get_packages_dir() -> str:
    """Get the packages directory from environment or default."""
    return os.environ.get("SANDBOX_PACKAGES_DIR", DEFAULT_PACKAGES_DIR)


def is_package_installed(package_name: str) -> tuple[bool, str | None]:
    """Check if a package is installed in the custom packages directory.

    Args:
        package_name: The PyPI package name

    Returns:
        Tuple of (is_installed, version or None)
    """
    packages_dir = get_packages_dir()

    # Add packages dir to sys.path temporarily for import check
    if packages_dir not in sys.path:
        sys.path.insert(0, packages_dir)

    try:
        # Try to get version from importlib.metadata
        from importlib.metadata import distributions, version

        # Check distributions in our packages directory
        for dist in distributions(path=[packages_dir]):
            if dist.metadata["Name"].lower() == package_name.lower():
                return True, dist.version

        # Also check globally (in case pip installed elsewhere)
        try:
            ver = version(package_name)
            return True, ver
        except Exception:
            pass

        return False, None
    except Exception as e:
        logger.debug(f"Error checking if {package_name} is installed: {e}")
        return False, None


async def install_package(
    module_name: str,
    version: str | None = None,
) -> InstallResult:
    """Install a package to the custom packages directory.

    Args:
        module_name: The module/import name
        version: Optional specific version to install

    Returns:
        InstallResult with status and details
    """
    # Check if it's a stdlib module
    if is_stdlib_module(module_name):
        return InstallResult(
            module_name=module_name,
            package_name=module_name,
            status=InstallStatus.NOT_REQUIRED,
        )

    # Get the PyPI package name
    package_name = await get_package_name_for_module(module_name)

    # Check if already installed
    installed, installed_version = is_package_installed(package_name)
    if installed:
        logger.info(
            f"Package {package_name} already installed (version {installed_version})"
        )
        return InstallResult(
            module_name=module_name,
            package_name=package_name,
            status=InstallStatus.INSTALLED,
            version=installed_version,
        )

    # Build the pip install command
    packages_dir = get_packages_dir()
    package_spec = f"{package_name}=={version}" if version else package_name

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        packages_dir,
        "--only-binary",
        ":all:",
        "--quiet",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        package_spec,
    ]

    logger.info(f"Installing package: {package_spec} to {packages_dir}")

    try:
        # Run pip install
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=300.0,  # 5 minute timeout
        )

        if process.returncode != 0:
            error_msg = stderr.decode().strip() or stdout.decode().strip()
            logger.error(f"Failed to install {package_name}: {error_msg}")
            return InstallResult(
                module_name=module_name,
                package_name=package_name,
                status=InstallStatus.FAILED,
                error_message=error_msg[:500],  # Truncate long errors
            )

        # Verify installation
        installed, installed_version = is_package_installed(package_name)
        if installed:
            logger.info(
                f"Successfully installed {package_name} version {installed_version}"
            )
            return InstallResult(
                module_name=module_name,
                package_name=package_name,
                status=InstallStatus.INSTALLED,
                version=installed_version,
            )
        else:
            logger.warning(
                f"Package {package_name} installed but not found in {packages_dir}"
            )
            return InstallResult(
                module_name=module_name,
                package_name=package_name,
                status=InstallStatus.INSTALLED,
            )

    except asyncio.TimeoutError:
        logger.error(f"Timeout installing {package_name}")
        return InstallResult(
            module_name=module_name,
            package_name=package_name,
            status=InstallStatus.FAILED,
            error_message="Installation timed out after 5 minutes",
        )
    except Exception as e:
        logger.error(f"Error installing {package_name}: {e}")
        return InstallResult(
            module_name=module_name,
            package_name=package_name,
            status=InstallStatus.FAILED,
            error_message=str(e),
        )


async def install_packages(module_names: list[str]) -> list[InstallResult]:
    """Install multiple packages.

    Args:
        module_names: List of module names to install

    Returns:
        List of InstallResult for each module
    """
    results = []
    for module_name in module_names:
        result = await install_package(module_name)
        results.append(result)
    return results


def list_installed_packages() -> list[dict[str, str]]:
    """List all packages installed in the custom packages directory.

    Returns:
        List of dicts with 'name' and 'version' keys
    """
    packages_dir = get_packages_dir()

    try:
        from importlib.metadata import distributions

        packages = []
        for dist in distributions(path=[packages_dir]):
            packages.append(
                {
                    "name": dist.metadata["Name"],
                    "version": dist.version,
                }
            )

        return sorted(packages, key=lambda p: p["name"].lower())
    except Exception as e:
        logger.error(f"Error listing installed packages: {e}")
        return []


def install_result_to_dict(result: InstallResult) -> dict:
    """Convert InstallResult to dictionary for JSON serialization."""
    return {
        "module_name": result.module_name,
        "package_name": result.package_name,
        "status": result.status.value,
        "version": result.version,
        "error_message": result.error_message,
    }
