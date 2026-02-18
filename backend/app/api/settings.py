"""Settings API endpoints.

Accessible without authentication (Option B architecture - admin panel is local-only).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_db
from app.schemas.setting import (
    SettingListResponse,
    SettingResponse,
)
from app.services.global_config import GlobalConfigService
from app.services.sandbox_client import SandboxClient, get_sandbox_client
from app.services.setting import SettingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# --- Security Policy ---

# Defines the valid security policy settings, their allowed values, and defaults.
SECURITY_POLICY_SETTINGS: dict[str, dict[str, Any]] = {
    "remote_tool_editing": {
        "default": "disabled",
        "allowed": ["disabled", "enabled"],
        "description": "Whether remote (Worker/tunnel) sessions can create, update, or delete tools and servers",
    },
    "tool_approval_mode": {
        "default": "require_approval",
        "allowed": ["require_approval", "auto_approve"],
        "description": "Whether new tools require admin approval or are auto-approved",
    },
    "network_access_policy": {
        "default": "require_approval",
        "allowed": ["require_approval", "allow_all_public"],
        "description": "Whether tools can access any public host, or only explicitly approved hosts",
    },
    "module_approval_mode": {
        "default": "require_approval",
        "allowed": ["require_approval", "auto_approve"],
        "description": "Whether module requests require admin approval or are auto-added to the allowlist",
    },
    "redact_secrets_in_output": {
        "default": "enabled",
        "allowed": ["enabled", "disabled"],
        "description": "Whether known secret values are scrubbed from tool output before returning to the LLM",
    },
    "log_retention_days": {
        "default": "30",
        "allowed": None,  # Numeric, validated separately
        "description": "How long execution logs are kept before cleanup (days)",
    },
    "mcp_rate_limit_rpm": {
        "default": "300",
        "allowed": None,  # Numeric, validated separately
        "description": "MCP gateway requests per minute (all remote users share one IP via cloudflared)",
    },
}


class SecurityPolicyResponse(BaseModel):
    """Response for security policy settings."""

    remote_tool_editing: str
    tool_approval_mode: str
    network_access_policy: str
    module_approval_mode: str
    redact_secrets_in_output: str
    log_retention_days: int
    mcp_rate_limit_rpm: int


class SecurityPolicyUpdate(BaseModel):
    """Request to update security policy settings."""

    remote_tool_editing: str | None = None
    tool_approval_mode: str | None = None
    network_access_policy: str | None = None
    module_approval_mode: str | None = None
    redact_secrets_in_output: str | None = None
    log_retention_days: int | None = Field(None, ge=1, le=3650)
    mcp_rate_limit_rpm: int | None = Field(None, ge=10, le=10000)


# --- Module Config Schemas ---


class ModuleConfigResponse(BaseModel):
    """Response for module configuration."""

    allowed_modules: list[str]
    default_modules: list[str]
    is_custom: bool


class UpdateModulesRequest(BaseModel):
    """Request to update allowed modules."""

    add_modules: list[str] | None = Field(None, description="Modules to add")
    remove_modules: list[str] | None = Field(None, description="Modules to remove")
    reset_to_defaults: bool | None = Field(None, description="Reset to default modules")


def get_setting_service(db: AsyncSession = Depends(get_db)) -> SettingService:
    """Dependency to get setting service."""
    return SettingService(db)


@router.get("", response_model=SettingListResponse)
async def list_settings(
    setting_service: SettingService = Depends(get_setting_service),
) -> SettingListResponse:
    """List all settings.

    NOTE: Encrypted values are masked for security.
    """
    settings = await setting_service.get_all()

    return SettingListResponse(
        settings=[
            SettingResponse(
                id=s.id,
                key=s.key,
                value=setting_service.mask_value(s),
                encrypted=s.encrypted,
                description=s.description,
                updated_at=s.updated_at,
            )
            for s in settings
        ]
    )


# --- Security Policy Endpoints ---


@router.get("/security-policy", response_model=SecurityPolicyResponse)
async def get_security_policy(
    setting_service: SettingService = Depends(get_setting_service),
) -> SecurityPolicyResponse:
    """Get all security policy settings with current values (or defaults)."""
    values: dict[str, str] = {}
    for key, meta in SECURITY_POLICY_SETTINGS.items():
        db_value = await setting_service.get_value(key, default=meta["default"])
        values[key] = db_value or meta["default"]

    return SecurityPolicyResponse(
        remote_tool_editing=values["remote_tool_editing"],
        tool_approval_mode=values["tool_approval_mode"],
        network_access_policy=values["network_access_policy"],
        module_approval_mode=values["module_approval_mode"],
        redact_secrets_in_output=values["redact_secrets_in_output"],
        log_retention_days=int(values["log_retention_days"]),
        mcp_rate_limit_rpm=int(values["mcp_rate_limit_rpm"]),
    )


@router.patch("/security-policy", response_model=SecurityPolicyResponse)
async def update_security_policy(
    request: SecurityPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    setting_service: SettingService = Depends(get_setting_service),
) -> SecurityPolicyResponse:
    """Update one or more security policy settings.

    Only provided fields are updated. Validates values against allowed options.
    """
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update",
        )

    for key, value in updates.items():
        meta = SECURITY_POLICY_SETTINGS[key]
        str_value = str(value)

        # Validate allowed values for enum-style settings
        if meta["allowed"] is not None and str_value not in meta["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid value '{str_value}' for {key}. Allowed: {meta['allowed']}",
            )

        await setting_service.set_value(
            key=key,
            value=str_value,
            description=meta["description"],
        )

    await db.commit()

    # If MCP rate limit was changed, update the in-memory rate limiter
    if "mcp_rate_limit_rpm" in updates:
        from app.middleware.rate_limit import RateLimiter

        RateLimiter.get_instance().update_mcp_config(int(updates["mcp_rate_limit_rpm"]))

    # Return the full current state
    return await get_security_policy(setting_service=setting_service)


# --- Module Configuration Endpoints ---


def get_global_config_service(db: AsyncSession = Depends(get_db)) -> GlobalConfigService:
    """Dependency to get global config service."""
    return GlobalConfigService(db)


@router.get("/modules", response_model=ModuleConfigResponse)
async def get_module_config(
    config_service: GlobalConfigService = Depends(get_global_config_service),
) -> ModuleConfigResponse:
    """Get the global module configuration."""
    allowed = await config_service.get_allowed_modules()
    is_custom = not await config_service.is_using_defaults()

    return ModuleConfigResponse(
        allowed_modules=sorted(allowed),
        default_modules=sorted(config_service.get_default_modules()),
        is_custom=is_custom,
    )


@router.patch("/modules", response_model=ModuleConfigResponse)
async def update_modules(
    request: UpdateModulesRequest,
    db: AsyncSession = Depends(get_db),
    config_service: GlobalConfigService = Depends(get_global_config_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ModuleConfigResponse:
    """Update the global allowed modules list.

    When adding modules, triggers package installation in the sandbox.
    """
    # Handle reset first
    if request.reset_to_defaults:
        await config_service.reset_to_defaults()
        await db.commit()
        allowed = await config_service.get_allowed_modules()

        # Trigger sandbox sync with new module list
        await sandbox_client.sync_packages(allowed)

        return ModuleConfigResponse(
            allowed_modules=sorted(allowed),
            default_modules=sorted(config_service.get_default_modules()),
            is_custom=False,
        )

    # Handle additions - install packages in sandbox
    if request.add_modules:
        for module_name in request.add_modules:
            await config_service.add_module(module_name)
            # Trigger package installation in sandbox
            install_result = await sandbox_client.install_package(module_name)
            if install_result.get("status") == "failed":
                logger.warning(
                    f"Package installation failed for {module_name}: "
                    f"{install_result.get('error_message')}"
                )

    # Handle removals
    if request.remove_modules:
        for module_name in request.remove_modules:
            await config_service.remove_module(module_name)

    await db.commit()

    allowed = await config_service.get_allowed_modules()
    is_custom = not await config_service.is_using_defaults()

    return ModuleConfigResponse(
        allowed_modules=sorted(allowed),
        default_modules=sorted(config_service.get_default_modules()),
        is_custom=is_custom,
    )


# --- Enhanced Module Endpoints ---


class ModuleInfoResponse(BaseModel):
    """Response for module information with status."""

    module_name: str
    package_name: str
    is_stdlib: bool
    is_installed: bool
    installed_version: str | None = None
    pypi_info: dict[str, Any] | None = None
    error: str | None = None


class EnhancedModuleConfigResponse(BaseModel):
    """Response for enhanced module configuration with install status."""

    allowed_modules: list[ModuleInfoResponse]
    default_modules: list[str]
    is_custom: bool
    installed_packages: list[dict[str, str]]


class ModuleInstallRequest(BaseModel):
    """Request to manually install a module."""

    version: str | None = None


class ModuleInstallResponse(BaseModel):
    """Response from module installation."""

    module_name: str
    package_name: str
    status: str
    version: str | None = None
    error_message: str | None = None


class PyPIInfoResponse(BaseModel):
    """Response for PyPI package information."""

    module_name: str
    package_name: str
    is_stdlib: bool
    pypi_info: dict[str, Any] | None = None
    error: str | None = None


@router.get("/modules/enhanced", response_model=EnhancedModuleConfigResponse)
async def get_enhanced_module_config(
    config_service: GlobalConfigService = Depends(get_global_config_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> EnhancedModuleConfigResponse:
    """Get enhanced module configuration with installation status.

    Returns module list with:
    - Whether each module is stdlib or third-party
    - Installation status for third-party packages
    - Installed version information
    """
    allowed = await config_service.get_allowed_modules()
    is_custom = not await config_service.is_using_defaults()

    # Get classification from sandbox
    classification = await sandbox_client.classify_modules(allowed)

    # Get installed packages
    installed_packages = await sandbox_client.list_installed_packages()

    # Build module info list
    modules_info = []
    for module_name in sorted(allowed):
        is_stdlib = module_name in classification.get("stdlib", [])

        if is_stdlib:
            modules_info.append(
                ModuleInfoResponse(
                    module_name=module_name,
                    package_name=module_name,
                    is_stdlib=True,
                    is_installed=True,  # stdlib is always available
                )
            )
        else:
            # Get package status from sandbox
            status = await sandbox_client.get_package_status(module_name)
            modules_info.append(
                ModuleInfoResponse(
                    module_name=module_name,
                    package_name=status.get("package_name", module_name),
                    is_stdlib=False,
                    is_installed=status.get("is_installed", False),
                    installed_version=status.get("installed_version"),
                    error=status.get("error"),
                )
            )

    return EnhancedModuleConfigResponse(
        allowed_modules=modules_info,
        default_modules=sorted(config_service.get_default_modules()),
        is_custom=is_custom,
        installed_packages=installed_packages,
    )


@router.get("/modules/pypi/{module_name}", response_model=PyPIInfoResponse)
async def get_pypi_info(
    module_name: str,
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> PyPIInfoResponse:
    """Get PyPI information for a module.

    Returns package metadata from PyPI, or indicates if it's a stdlib module.
    Useful for previewing what package will be installed.
    """
    result = await sandbox_client.get_pypi_info(module_name)

    return PyPIInfoResponse(
        module_name=result.get("module_name", module_name),
        package_name=result.get("package_name", module_name),
        is_stdlib=result.get("is_stdlib", False),
        pypi_info=result.get("pypi_info"),
        error=result.get("error"),
    )


@router.post("/modules/{module_name}/install", response_model=ModuleInstallResponse)
async def install_module(
    module_name: str,
    request: ModuleInstallRequest | None = None,
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> ModuleInstallResponse:
    """Manually trigger installation of a module.

    Use this to retry failed installations or install a specific version.
    """
    version = request.version if request else None
    result = await sandbox_client.install_package(module_name, version)

    return ModuleInstallResponse(
        module_name=result.get("module_name", module_name),
        package_name=result.get("package_name", module_name),
        status=result.get("status", "failed"),
        version=result.get("version"),
        error_message=result.get("error_message"),
    )


@router.post("/modules/sync")
async def sync_modules(
    config_service: GlobalConfigService = Depends(get_global_config_service),
    sandbox_client: SandboxClient = Depends(get_sandbox_client),
) -> dict[str, Any]:
    """Manually trigger a sync of all modules.

    Installs any missing third-party packages in the sandbox.
    """
    allowed = await config_service.get_allowed_modules()
    result = await sandbox_client.sync_packages(allowed)

    return {
        "success": result.get("failed_count", 0) == 0,
        "installed_count": result.get("installed_count", 0),
        "failed_count": result.get("failed_count", 0),
        "stdlib_count": result.get("stdlib_count", 0),
        "results": result.get("results", []),
    }
