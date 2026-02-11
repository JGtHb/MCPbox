"""Security Audit Logging Service.

Logs security-relevant events for compliance and monitoring:
- Credential modifications
- Tunnel configuration changes
"""

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from app.services.activity_logger import ActivityLoggerService, get_activity_logger

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Security audit action types."""

    # Credential events (used by credentials API)
    CREDENTIAL_CREATE = "credential.create"
    CREDENTIAL_UPDATE = "credential.update"
    CREDENTIAL_DELETE = "credential.delete"

    # Tunnel events (used by tunnel API)
    TUNNEL_START = "tunnel.start"
    TUNNEL_STOP = "tunnel.stop"
    TUNNEL_CONFIG_UPDATE = "tunnel.config_update"

    # System events
    CLEANUP_OLD_LOGS = "system.cleanup_logs"


class AuditService:
    """Service for logging security audit events.

    All audit logs include:
    - Timestamp
    - Action type
    - Resource ID (when applicable)
    - Actor (IP address, future: user ID)
    - Details about the change
    """

    def __init__(self, activity_logger: ActivityLoggerService | None = None):
        self._logger = activity_logger or get_activity_logger()

    async def log(
        self,
        action: AuditAction,
        resource_type: str,
        resource_id: UUID | None = None,
        server_id: UUID | None = None,
        details: dict[str, Any] | None = None,
        actor_ip: str | None = None,
        level: str = "info",
    ) -> dict:
        """Log a security audit event.

        Args:
            action: The audit action type
            resource_type: Type of resource (credential, server, tool, etc.)
            resource_id: ID of the affected resource
            server_id: Associated server ID if applicable
            details: Additional audit details
            actor_ip: IP address of the actor
            level: Log level (info, warning, error)

        Returns:
            The created audit log entry
        """
        message = f"{action.value}: {resource_type}"
        if resource_id:
            message += f" ({resource_id})"

        audit_details = {
            "action": action.value,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if actor_ip:
            audit_details["actor_ip"] = actor_ip

        if details:
            # Sanitize sensitive data
            safe_details = self._sanitize_details(details)
            audit_details["changes"] = safe_details

        return await self._logger.log(
            log_type="audit",
            message=message,
            server_id=server_id,
            level=level,
            details=audit_details,
        )

    def _sanitize_details(self, details: dict[str, Any]) -> dict[str, Any]:
        """Remove sensitive data from audit details.

        Redacts passwords, tokens, API keys, etc.
        """
        sensitive_keys = {
            "password",
            "secret",
            "token",
            "api_key",
            "access_token",
            "refresh_token",
            "client_secret",
            "value",  # Generic credential value
        }

        sanitized = {}
        for key, value in details.items():
            key_lower = key.lower()
            if any(s in key_lower for s in sensitive_keys):
                # Mark as redacted but indicate if value was set/unset
                if value is not None:
                    sanitized[key] = "[REDACTED - set]"
                else:
                    sanitized[key] = "[REDACTED - unset]"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_details(value)
            else:
                sanitized[key] = value

        return sanitized

    # Convenience methods for common audit events

    async def log_credential_create(
        self,
        credential_id: UUID,
        server_id: UUID,
        credential_name: str,
        auth_type: str,
        actor_ip: str | None = None,
    ) -> dict:
        """Log credential creation."""
        return await self.log(
            action=AuditAction.CREDENTIAL_CREATE,
            resource_type="credential",
            resource_id=credential_id,
            server_id=server_id,
            details={
                "name": credential_name,
                "auth_type": auth_type,
            },
            actor_ip=actor_ip,
        )

    async def log_credential_update(
        self,
        credential_id: UUID,
        server_id: UUID | None,
        changes: dict[str, Any],
        actor_ip: str | None = None,
    ) -> dict:
        """Log credential update."""
        return await self.log(
            action=AuditAction.CREDENTIAL_UPDATE,
            resource_type="credential",
            resource_id=credential_id,
            server_id=server_id,
            details={"changes": changes},
            actor_ip=actor_ip,
        )

    async def log_credential_delete(
        self,
        credential_id: UUID,
        credential_name: str,
        server_id: UUID | None,
        actor_ip: str | None = None,
    ) -> dict:
        """Log credential deletion."""
        return await self.log(
            action=AuditAction.CREDENTIAL_DELETE,
            resource_type="credential",
            resource_id=credential_id,
            server_id=server_id,
            details={"name": credential_name},
            actor_ip=actor_ip,
            level="warning",
        )

    async def log_tunnel_action(
        self,
        action: AuditAction,
        details: dict | None = None,
        actor_ip: str | None = None,
    ) -> dict:
        """Log tunnel start/stop/config change."""
        level = "warning" if action == AuditAction.TUNNEL_STOP else "info"
        return await self.log(
            action=action,
            resource_type="tunnel",
            details=details,
            actor_ip=actor_ip,
            level=level,
        )


# Dependency injection helper
_audit_service: AuditService | None = None


def get_audit_service() -> AuditService:
    """Get the audit service singleton."""
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
