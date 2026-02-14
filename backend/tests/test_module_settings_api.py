"""Tests for module settings API endpoints."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.services.sandbox_client import get_sandbox_client


@pytest.fixture
def mock_sandbox_client():
    """Create a mock sandbox client."""
    mock_client = MagicMock()
    # Set up default async mock methods
    mock_client.install_package = AsyncMock(return_value={
        "module_name": "test_module",
        "package_name": "test_module",
        "status": "installed",
        "version": "1.0.0",
    })
    mock_client.sync_packages = AsyncMock(return_value={
        "installed_count": 0,
        "failed_count": 0,
        "stdlib_count": 0,
        "results": [],
    })
    mock_client.classify_modules = AsyncMock(return_value={
        "stdlib": ["json", "os"],
        "third_party": [],
    })
    mock_client.list_installed_packages = AsyncMock(return_value=[])
    mock_client.get_package_status = AsyncMock(return_value={
        "is_installed": False,
        "package_name": "test",
    })
    mock_client.get_pypi_info = AsyncMock(return_value={
        "module_name": "test",
        "package_name": "test",
        "is_stdlib": True,
        "pypi_info": None,
    })
    return mock_client


@pytest.fixture(autouse=True)
def override_sandbox_client(mock_sandbox_client):
    """Override the sandbox client dependency for all tests in this module."""
    app.dependency_overrides[get_sandbox_client] = lambda: mock_sandbox_client
    yield
    app.dependency_overrides.pop(get_sandbox_client, None)


class TestModuleConfigEndpoints:
    """Tests for /settings/modules endpoints."""

    @pytest.mark.asyncio
    async def test_get_module_config_defaults(self, async_client: AsyncClient, admin_headers):
        """Test getting module config when using defaults."""
        response = await async_client.get("/api/settings/modules", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "allowed_modules" in data
        assert "default_modules" in data
        assert "is_custom" in data
        assert isinstance(data["allowed_modules"], list)
        assert isinstance(data["default_modules"], list)
        # When using defaults, is_custom should be False
        assert data["is_custom"] is False
        # Should have some modules
        assert len(data["allowed_modules"]) > 0
        # allowed_modules should match default_modules when using defaults
        assert sorted(data["allowed_modules"]) == sorted(data["default_modules"])

    @pytest.mark.asyncio
    async def test_add_module(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test adding a module to the allowed list."""
        mock_sandbox_client.install_package = AsyncMock(return_value={
            "module_name": "test_module",
            "package_name": "test_module",
            "status": "installed",
            "version": "1.0.0",
        })

        response = await async_client.patch(
            "/api/settings/modules", json={"add_modules": ["test_module"]},
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "test_module" in data["allowed_modules"]
        assert data["is_custom"] is True

    @pytest.mark.asyncio
    async def test_remove_module(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test removing a module from the allowed list."""
        # First add a module
        mock_sandbox_client.install_package = AsyncMock(return_value={"status": "installed"})
        await async_client.patch(
            "/api/settings/modules", json={"add_modules": ["module_to_remove"]},
            headers=admin_headers
        )

        # Now remove it
        response = await async_client.patch(
            "/api/settings/modules", json={"remove_modules": ["module_to_remove"]},
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "module_to_remove" not in data["allowed_modules"]

    @pytest.mark.asyncio
    async def test_reset_to_defaults(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test resetting modules to defaults."""
        # First add a custom module
        mock_sandbox_client.install_package = AsyncMock(return_value={"status": "installed"})
        await async_client.patch(
            "/api/settings/modules", json={"add_modules": ["custom_module"]},
            headers=admin_headers
        )

        # Now reset to defaults
        mock_sandbox_client.sync_packages = AsyncMock(return_value={
            "installed_count": 0,
            "failed_count": 0,
            "stdlib_count": 0,
        })

        response = await async_client.patch(
            "/api/settings/modules", json={"reset_to_defaults": True},
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_custom"] is False
        assert "custom_module" not in data["allowed_modules"]


class TestEnhancedModuleConfig:
    """Tests for /settings/modules/enhanced endpoint."""

    @pytest.mark.asyncio
    async def test_get_enhanced_module_config(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test getting enhanced module config with install status."""
        mock_sandbox_client.classify_modules = AsyncMock(
            return_value={"stdlib": ["json", "os"], "third_party": []}
        )
        mock_sandbox_client.list_installed_packages = AsyncMock(return_value=[])
        mock_sandbox_client.get_package_status = AsyncMock(return_value={
            "is_installed": False,
            "package_name": "test",
        })

        response = await async_client.get("/api/settings/modules/enhanced", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "allowed_modules" in data
        assert "default_modules" in data
        assert "is_custom" in data
        assert "installed_packages" in data
        # Each module should have detailed info
        if data["allowed_modules"]:
            module = data["allowed_modules"][0]
            assert "module_name" in module
            assert "package_name" in module
            assert "is_stdlib" in module
            assert "is_installed" in module


class TestPyPIInfo:
    """Tests for /settings/modules/pypi/{module_name} endpoint."""

    @pytest.mark.asyncio
    async def test_get_pypi_info_stdlib(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test getting PyPI info for a stdlib module."""
        mock_sandbox_client.get_pypi_info = AsyncMock(return_value={
            "module_name": "json",
            "package_name": "json",
            "is_stdlib": True,
            "pypi_info": None,
        })

        response = await async_client.get("/api/settings/modules/pypi/json", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["module_name"] == "json"
        assert data["is_stdlib"] is True
        assert data["pypi_info"] is None

    @pytest.mark.asyncio
    async def test_get_pypi_info_third_party(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test getting PyPI info for a third-party module."""
        mock_sandbox_client.get_pypi_info = AsyncMock(return_value={
            "module_name": "requests",
            "package_name": "requests",
            "is_stdlib": False,
            "pypi_info": {
                "name": "requests",
                "version": "2.31.0",
                "summary": "Python HTTP for Humans.",
            },
        })

        response = await async_client.get("/api/settings/modules/pypi/requests", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["module_name"] == "requests"
        assert data["is_stdlib"] is False
        assert data["pypi_info"] is not None
        assert data["pypi_info"]["name"] == "requests"


class TestModuleInstall:
    """Tests for /settings/modules/{module_name}/install endpoint."""

    @pytest.mark.asyncio
    async def test_install_module(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test manually installing a module."""
        mock_sandbox_client.install_package = AsyncMock(return_value={
            "module_name": "six",
            "package_name": "six",
            "status": "installed",
            "version": "1.16.0",
        })

        response = await async_client.post("/api/settings/modules/six/install", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["module_name"] == "six"
        assert data["status"] == "installed"

    @pytest.mark.asyncio
    async def test_install_module_with_version(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test installing a specific version of a module."""
        mock_sandbox_client.install_package = AsyncMock(return_value={
            "module_name": "six",
            "package_name": "six",
            "status": "installed",
            "version": "1.15.0",
        })

        response = await async_client.post(
            "/api/settings/modules/six/install", json={"version": "1.15.0"},
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1.15.0"


class TestModuleSync:
    """Tests for /settings/modules/sync endpoint."""

    @pytest.mark.asyncio
    async def test_sync_modules(self, async_client: AsyncClient, admin_headers, mock_sandbox_client):
        """Test syncing all modules."""
        mock_sandbox_client.sync_packages = AsyncMock(return_value={
            "installed_count": 2,
            "failed_count": 0,
            "stdlib_count": 5,
            "results": [],
        })

        response = await async_client.post("/api/settings/modules/sync", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "installed_count" in data
        assert "failed_count" in data
        assert "stdlib_count" in data
        assert data["success"] is True
        assert data["installed_count"] == 2
