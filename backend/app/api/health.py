"""Health check endpoint with database connectivity check and circuit breaker status.

All health endpoints are accessible without authentication since the admin panel
is only exposed locally (Option B architecture).
"""

from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core import check_db_connection, settings
from app.core.retry import CircuitBreaker
from app.services.sandbox_client import get_sandbox_client

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str
    sandbox: str = "disconnected"


class HealthDetailResponse(HealthResponse):
    """Detailed health check response.

    Same as base response - environment field was removed for security.
    """


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        status.HTTP_200_OK: {"description": "Service is healthy"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Service is unhealthy"},
    },
)
async def health_check(response: Response) -> HealthResponse:
    """
    Health check endpoint.

    Returns the service health status including database and sandbox connectivity.
    Returns 503 if the database is unavailable.
    """
    db_healthy = await check_db_connection()
    sandbox_client = get_sandbox_client()
    sandbox_healthy = await sandbox_client.health_check()

    # Set appropriate status code for container orchestration
    if not db_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="healthy" if db_healthy else "unhealthy",
        version=settings.app_version,
        database="connected" if db_healthy else "disconnected",
        sandbox="connected" if sandbox_healthy else "disconnected",
    )


@router.get(
    "/health/detail",
    response_model=HealthDetailResponse,
    responses={
        status.HTTP_200_OK: {"description": "Detailed health information"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Service is unhealthy"},
    },
)
async def health_detail(response: Response) -> HealthDetailResponse:
    """
    Detailed health check endpoint.

    Returns extended health information.
    Returns 503 if the database is unavailable.
    """
    db_healthy = await check_db_connection()
    sandbox_client = get_sandbox_client()
    sandbox_healthy = await sandbox_client.health_check()

    if not db_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthDetailResponse(
        status="healthy" if db_healthy else "unhealthy",
        version=settings.app_version,
        database="connected" if db_healthy else "disconnected",
        sandbox="connected" if sandbox_healthy else "disconnected",
    )


@router.get("/health/services")
async def service_health(response: Response) -> dict[str, Any]:
    """Check health of all connected services.

    Returns status of database, sandbox, and circuit breakers.
    """
    db_healthy = await check_db_connection()
    sandbox_client = get_sandbox_client()
    sandbox_healthy = await sandbox_client.health_check()

    overall_healthy = db_healthy and sandbox_healthy
    if not overall_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "services": {
            "database": {
                "status": "connected" if db_healthy else "disconnected",
                "healthy": db_healthy,
            },
            "sandbox": {
                "status": "connected" if sandbox_healthy else "disconnected",
                "healthy": sandbox_healthy,
                "circuit_breaker": sandbox_client.get_circuit_state(),
            },
        },
    }


@router.get("/health/circuits")
async def get_circuit_states() -> dict[str, Any]:
    """Get all circuit breaker states.

    Returns the current state of all circuit breakers in the system.
    Useful for monitoring and debugging connection issues.
    """
    return {
        "circuits": CircuitBreaker.get_all_states(),
    }


@router.post("/health/circuits/reset")
async def reset_all_circuits() -> dict[str, str]:
    """Reset all circuit breakers to closed state.

    Use this to manually recover from circuit breaker trips
    when you know the underlying issue has been resolved.
    """
    await CircuitBreaker.reset_all()
    return {"message": "All circuit breakers reset"}


@router.post("/health/circuits/{service_name}/reset")
async def reset_circuit(service_name: str) -> dict[str, Any]:
    """Reset a specific circuit breaker.

    Args:
        service_name: Name of the service circuit breaker to reset
    """
    circuit = CircuitBreaker.get_or_create(service_name)
    await circuit.reset()
    return {
        "message": f"Circuit breaker for {service_name} reset",
        "state": circuit.get_state(),
    }


class ConfigResponse(BaseModel):
    """Configuration response for frontend."""

    auth_required: bool
    version: str
    app_name: str


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Get public configuration for the frontend.

    This endpoint is NOT protected by admin auth since the frontend needs
    to call it to determine if authentication is required.

    Returns:
        Configuration including whether admin auth is required.
    """
    return ConfigResponse(
        auth_required=True,  # Admin API key is always required
        version=settings.app_version,
        app_name=settings.app_name,
    )
