"""Approval service for tool publishing, module requests, and network access requests."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.module_request import ModuleRequest
from app.models.network_access_request import NetworkAccessRequest
from app.models.tool import Tool

logger = logging.getLogger(__name__)


class ApprovalService:
    """Service for managing tool approval workflow and whitelist requests."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Tool Approval Workflow
    # =========================================================================

    async def request_publish(
        self,
        tool_id: UUID,
        notes: str | None = None,
        requested_by: str | None = None,
    ) -> Tool:
        """Request approval to publish a tool.

        Args:
            tool_id: ID of the tool to request publish for
            notes: Notes for the reviewer
            requested_by: Email of the requester (from JWT)

        Returns:
            Updated tool

        Raises:
            ValueError: If tool not found or not in draft/rejected status
        """
        stmt = select(Tool).where(Tool.id == tool_id)
        result = await self.db.execute(stmt)
        tool = result.scalar_one_or_none()

        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        if tool.approval_status not in ("draft", "rejected"):
            raise ValueError(
                f"Tool must be in 'draft' or 'rejected' status to request publish. "
                f"Current status: {tool.approval_status}"
            )

        tool.approval_requested_at = datetime.now(UTC)
        tool.publish_notes = notes
        tool.rejection_reason = None  # Clear any previous rejection reason

        if requested_by and not tool.created_by:
            tool.created_by = requested_by

        # Check if auto-approve is enabled
        from app.services.setting import SettingService

        setting_service = SettingService(self.db)
        approval_mode = await setting_service.get_value(
            "tool_approval_mode", default="require_approval"
        )

        if approval_mode == "auto_approve":
            tool.approval_status = "approved"
            tool.approved_at = datetime.now(UTC)
            tool.approved_by = "auto_approve"
            logger.info(
                f"Tool {tool.name} ({tool_id}) auto-approved (tool_approval_mode=auto_approve)"
            )
        else:
            tool.approval_status = "pending_review"
            logger.info(f"Tool {tool.name} ({tool_id}) requested publish by {requested_by}")

        await self.db.commit()
        await self.db.refresh(tool)

        return tool

    async def approve_tool(
        self,
        tool_id: UUID,
        approved_by: str,
        reason: str | None = None,
    ) -> Tool:
        """Approve a tool for publishing.

        Args:
            tool_id: ID of the tool to approve
            approved_by: Email of the admin approving
            reason: Optional approval notes

        Returns:
            Updated tool

        Raises:
            ValueError: If tool not found or not pending review
        """
        # Eagerly load server relationship for post-approval refresh
        stmt = select(Tool).where(Tool.id == tool_id).options(selectinload(Tool.server))
        result = await self.db.execute(stmt)
        tool = result.scalar_one_or_none()

        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        if tool.approval_status != "pending_review":
            raise ValueError(
                f"Tool must be in 'pending_review' status to approve. "
                f"Current status: {tool.approval_status}"
            )

        tool.approval_status = "approved"
        tool.approved_at = datetime.now(UTC)
        tool.approved_by = approved_by
        tool.rejection_reason = None

        await self.db.commit()
        await self.db.refresh(tool, attribute_names=["server"])

        logger.info(f"Tool {tool.name} ({tool_id}) approved by {approved_by}")
        return tool

    async def reject_tool(
        self,
        tool_id: UUID,
        rejected_by: str,
        reason: str,
    ) -> Tool:
        """Reject a tool's publish request.

        Args:
            tool_id: ID of the tool to reject
            rejected_by: Email of the admin rejecting
            reason: Reason for rejection (required)

        Returns:
            Updated tool

        Raises:
            ValueError: If tool not found or not pending review
        """
        stmt = select(Tool).where(Tool.id == tool_id)
        result = await self.db.execute(stmt)
        tool = result.scalar_one_or_none()

        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        if tool.approval_status != "pending_review":
            raise ValueError(
                f"Tool must be in 'pending_review' status to reject. "
                f"Current status: {tool.approval_status}"
            )

        tool.approval_status = "rejected"
        tool.approved_at = None
        tool.approved_by = None
        tool.rejection_reason = reason

        await self.db.commit()
        await self.db.refresh(tool)

        logger.info(f"Tool {tool.name} ({tool_id}) rejected by {rejected_by}: {reason}")
        return tool

    async def get_pending_tools(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get tools by approval status.

        Args:
            page: Page number (1-indexed)
            page_size: Items per page
            search: Optional search term to filter by tool name, description, or server name
            status: Filter by status. None or "pending_review" for pending only,
                    "all" for all statuses, or specific status value.

        Returns:
            Tuple of (items, total_count)
        """
        from app.models import Server

        # Determine status filter
        status_filter: ColumnElement[bool]
        if status and status != "pending_review":
            if status == "all":
                status_filter = Tool.approval_status.in_(["draft", "pending_review", "approved", "rejected"])
            else:
                status_filter = Tool.approval_status == status
        else:
            status_filter = Tool.approval_status == "pending_review"

        # Count total
        if search:
            count_stmt = (
                select(func.count(Tool.id))
                .select_from(Tool)
                .outerjoin(Server, Tool.server_id == Server.id)
                .where(
                    status_filter,
                    or_(
                        Tool.name.ilike(f"%{search}%"),
                        Tool.description.ilike(f"%{search}%"),
                        Server.name.ilike(f"%{search}%"),
                    ),
                )
            )
        else:
            count_stmt = select(func.count(Tool.id)).where(status_filter)
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        # Get items with server info
        if search:
            stmt = (
                select(Tool)
                .options(selectinload(Tool.server))
                .outerjoin(Server, Tool.server_id == Server.id)
                .where(
                    status_filter,
                    or_(
                        Tool.name.ilike(f"%{search}%"),
                        Tool.description.ilike(f"%{search}%"),
                        Server.name.ilike(f"%{search}%"),
                    ),
                )
                .order_by(Tool.approval_requested_at.desc().nullslast())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        else:
            stmt = (
                select(Tool)
                .options(selectinload(Tool.server))
                .where(status_filter)
                .order_by(Tool.approval_requested_at.desc().nullslast())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        result = await self.db.execute(stmt)
        tools = result.scalars().all()

        items = [
            {
                "id": tool.id,
                "server_id": tool.server_id,
                "server_name": tool.server.name if tool.server else "Unknown",
                "name": tool.name,
                "description": tool.description,
                "python_code": tool.python_code,
                "created_by": tool.created_by,
                "publish_notes": tool.publish_notes,
                "approval_status": tool.approval_status,
                "approval_requested_at": tool.approval_requested_at,
                "approved_at": tool.approved_at,
                "approved_by": tool.approved_by,
                "rejection_reason": tool.rejection_reason,
                "current_version": tool.current_version,
            }
            for tool in tools
        ]

        return items, total

    # =========================================================================
    # Module Request Management
    # =========================================================================

    async def create_module_request(
        self,
        tool_id: UUID,
        module_name: str,
        justification: str,
        requested_by: str | None = None,
    ) -> ModuleRequest:
        """Create a request to whitelist a Python module.

        Args:
            tool_id: ID of the tool that needs this module
            module_name: Name of the module to whitelist
            justification: Why the module is needed
            requested_by: Email of the requester

        Returns:
            Created module request

        Raises:
            ValueError: If tool not found or duplicate request exists
        """
        # Verify tool exists
        stmt = select(Tool).where(Tool.id == tool_id)
        result = await self.db.execute(stmt)
        tool = result.scalar_one_or_none()

        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        request = ModuleRequest(
            tool_id=tool_id,
            module_name=module_name,
            justification=justification,
            requested_by=requested_by,
            status="pending",
        )

        self.db.add(request)

        try:
            await self.db.commit()
        except IntegrityError as e:
            # Database constraint prevents duplicate pending requests
            # This is atomic and race-condition safe
            await self.db.rollback()
            raise ValueError(
                f"A pending request for module '{module_name}' already exists for this tool"
            ) from e

        await self.db.refresh(request)

        logger.info(f"Module request created: {module_name} for tool {tool.name} by {requested_by}")
        return request

    async def approve_module_request(
        self,
        request_id: UUID,
        approved_by: str,
    ) -> ModuleRequest:
        """Approve a module whitelist request and add to server's allowed modules.

        Args:
            request_id: ID of the request to approve
            approved_by: Email of the admin approving

        Returns:
            Updated module request

        Raises:
            ValueError: If request not found or not pending
        """
        stmt = (
            select(ModuleRequest)
            .options(selectinload(ModuleRequest.tool).selectinload(Tool.server))
            .where(ModuleRequest.id == request_id)
        )
        result = await self.db.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            raise ValueError(f"Module request {request_id} not found")

        if request.status != "pending":
            raise ValueError(f"Request must be in 'pending' status. Current: {request.status}")

        # Update request status
        request.status = "approved"
        request.reviewed_at = datetime.now(UTC)
        request.reviewed_by = approved_by

        # Add module to global allowed modules
        from app.services.global_config import GlobalConfigService

        config_service = GlobalConfigService(self.db)
        await config_service.add_module(request.module_name)

        await self.db.commit()
        await self.db.refresh(request)

        logger.info(
            f"Module request approved: {request.module_name} added globally by {approved_by}"
        )

        # Trigger package installation in sandbox (non-blocking)
        try:
            from app.services.sandbox_client import SandboxClient

            sandbox_client = SandboxClient.get_instance()
            install_result = await sandbox_client.install_package(request.module_name)
            if install_result.get("status") == "installed":
                logger.info(
                    f"Package {install_result.get('package_name', request.module_name)} "
                    f"installed successfully (version: {install_result.get('version', 'unknown')})"
                )
            elif install_result.get("status") == "not_required":
                logger.info(
                    f"Module {request.module_name} is a stdlib module, no installation needed"
                )
            else:
                logger.warning(
                    f"Package installation status: {install_result.get('status')}, "
                    f"error: {install_result.get('error_message', 'unknown')}"
                )
        except Exception as e:
            # Log but don't fail the approval if installation fails
            # Package can be installed manually later
            logger.warning(f"Failed to install package for {request.module_name}: {e}")

        return request

    async def reject_module_request(
        self,
        request_id: UUID,
        rejected_by: str,
        reason: str,
    ) -> ModuleRequest:
        """Reject a module whitelist request.

        Args:
            request_id: ID of the request to reject
            rejected_by: Email of the admin rejecting
            reason: Reason for rejection

        Returns:
            Updated module request
        """
        stmt = select(ModuleRequest).where(ModuleRequest.id == request_id)
        result = await self.db.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            raise ValueError(f"Module request {request_id} not found")

        if request.status != "pending":
            raise ValueError(f"Request must be in 'pending' status. Current: {request.status}")

        request.status = "rejected"
        request.reviewed_at = datetime.now(UTC)
        request.reviewed_by = rejected_by
        request.rejection_reason = reason

        await self.db.commit()
        await self.db.refresh(request)

        logger.info(f"Module request rejected: {request.module_name} by {rejected_by}")
        return request

    async def get_pending_module_requests(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get module requests filtered by status.

        Args:
            page: Page number (1-indexed)
            page_size: Items per page
            search: Optional search term to filter by module name or justification
            status: Filter by status. None or "pending" for pending only,
                    "all" for all statuses, or specific status value.

        Returns:
            Tuple of (items, total_count)
        """
        # Build base query conditions
        conditions: list[ColumnElement[bool]]
        if status and status != "pending":
            if status == "all":
                conditions = [ModuleRequest.status.in_(["pending", "approved", "rejected"])]
            else:
                conditions = [ModuleRequest.status == status]
        else:
            conditions = [ModuleRequest.status == "pending"]

        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    ModuleRequest.module_name.ilike(search_term),
                    ModuleRequest.justification.ilike(search_term),
                )
            )

        count_stmt = select(func.count(ModuleRequest.id)).where(*conditions)
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(ModuleRequest)
            .options(selectinload(ModuleRequest.tool).selectinload(Tool.server))
            .where(*conditions)
            .order_by(ModuleRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        requests = result.scalars().all()

        items = [
            {
                "id": req.id,
                "tool_id": req.tool_id,
                "tool_name": req.tool.name if req.tool else "Unknown",
                "server_id": req.tool.server_id if req.tool else None,
                "server_name": req.tool.server.name if req.tool and req.tool.server else "Unknown",
                "module_name": req.module_name,
                "justification": req.justification,
                "requested_by": req.requested_by,
                "status": req.status,
                "reviewed_by": req.reviewed_by,
                "reviewed_at": req.reviewed_at,
                "rejection_reason": req.rejection_reason,
                "created_at": req.created_at,
            }
            for req in requests
        ]

        return items, total

    async def get_module_requests_for_tool(
        self,
        tool_id: UUID,
    ) -> list[ModuleRequest]:
        """Get all module requests for a specific tool."""
        stmt = (
            select(ModuleRequest)
            .where(ModuleRequest.tool_id == tool_id)
            .order_by(ModuleRequest.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # =========================================================================
    # Network Access Request Management
    # =========================================================================

    async def create_network_access_request(
        self,
        tool_id: UUID,
        host: str,
        port: int | None,
        justification: str,
        requested_by: str | None = None,
    ) -> NetworkAccessRequest:
        """Create a request to whitelist network access.

        Args:
            tool_id: ID of the tool that needs this access
            host: Hostname or IP to whitelist
            port: Optional port restriction
            justification: Why the access is needed
            requested_by: Email of the requester

        Returns:
            Created network access request

        Raises:
            ValueError: If tool not found or duplicate request exists
        """
        # Verify tool exists
        stmt = select(Tool).where(Tool.id == tool_id)
        result = await self.db.execute(stmt)
        tool = result.scalar_one_or_none()

        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        request = NetworkAccessRequest(
            tool_id=tool_id,
            host=host,
            port=port,
            justification=justification,
            requested_by=requested_by,
            status="pending",
        )

        self.db.add(request)

        try:
            await self.db.commit()
        except IntegrityError as e:
            # Database constraint prevents duplicate pending requests
            # This is atomic and race-condition safe
            await self.db.rollback()
            port_str = f":{port}" if port else ""
            raise ValueError(
                f"A pending request for host '{host}{port_str}' already exists for this tool"
            ) from e

        await self.db.refresh(request)

        logger.info(
            f"Network access request created: {host} for tool {tool.name} by {requested_by}"
        )
        return request

    async def approve_network_access_request(
        self,
        request_id: UUID,
        approved_by: str,
    ) -> NetworkAccessRequest:
        """Approve a network access request and add to server's allowed hosts.

        Args:
            request_id: ID of the request to approve
            approved_by: Email of the admin approving

        Returns:
            Updated network access request
        """
        stmt = (
            select(NetworkAccessRequest)
            .options(selectinload(NetworkAccessRequest.tool).selectinload(Tool.server))
            .where(NetworkAccessRequest.id == request_id)
        )
        result = await self.db.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            raise ValueError(f"Network access request {request_id} not found")

        if request.status != "pending":
            raise ValueError(f"Request must be in 'pending' status. Current: {request.status}")

        # Update request status
        request.status = "approved"
        request.reviewed_at = datetime.now(UTC)
        request.reviewed_by = approved_by

        # Add host to server's allowed hosts
        server = request.tool.server

        # Switch server to allowlist mode if not already
        if server.network_mode == "isolated":
            server.network_mode = "allowlist"

        if server.allowed_hosts is None:
            server.allowed_hosts = []

        # Add host (with optional port) to allowed hosts
        host_entry = request.host
        if host_entry not in server.allowed_hosts:
            server.allowed_hosts = server.allowed_hosts + [host_entry]

        await self.db.commit()
        await self.db.refresh(request)

        logger.info(
            f"Network access request approved: {request.host} added to {server.name} by {approved_by}"
        )
        return request

    async def reject_network_access_request(
        self,
        request_id: UUID,
        rejected_by: str,
        reason: str,
    ) -> NetworkAccessRequest:
        """Reject a network access request.

        Args:
            request_id: ID of the request to reject
            rejected_by: Email of the admin rejecting
            reason: Reason for rejection

        Returns:
            Updated network access request
        """
        stmt = select(NetworkAccessRequest).where(NetworkAccessRequest.id == request_id)
        result = await self.db.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            raise ValueError(f"Network access request {request_id} not found")

        if request.status != "pending":
            raise ValueError(f"Request must be in 'pending' status. Current: {request.status}")

        request.status = "rejected"
        request.reviewed_at = datetime.now(UTC)
        request.reviewed_by = rejected_by
        request.rejection_reason = reason

        await self.db.commit()
        await self.db.refresh(request)

        logger.info(f"Network access request rejected: {request.host} by {rejected_by}")
        return request

    async def get_pending_network_access_requests(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get network access requests filtered by status.

        Args:
            page: Page number (1-indexed)
            page_size: Items per page
            search: Optional search term to filter by host or justification
            status: Filter by status. None or "pending" for pending only,
                    "all" for all statuses, or specific status value.

        Returns:
            Tuple of (items, total_count)
        """
        # Build base query conditions
        conditions: list[ColumnElement[bool]]
        if status and status != "pending":
            if status == "all":
                conditions = [NetworkAccessRequest.status.in_(["pending", "approved", "rejected"])]
            else:
                conditions = [NetworkAccessRequest.status == status]
        else:
            conditions = [NetworkAccessRequest.status == "pending"]

        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    NetworkAccessRequest.host.ilike(search_term),
                    NetworkAccessRequest.justification.ilike(search_term),
                )
            )

        count_stmt = select(func.count(NetworkAccessRequest.id)).where(*conditions)
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(NetworkAccessRequest)
            .options(selectinload(NetworkAccessRequest.tool).selectinload(Tool.server))
            .where(*conditions)
            .order_by(NetworkAccessRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        requests = result.scalars().all()

        items = [
            {
                "id": req.id,
                "tool_id": req.tool_id,
                "tool_name": req.tool.name if req.tool else "Unknown",
                "server_id": req.tool.server_id if req.tool else None,
                "server_name": req.tool.server.name if req.tool and req.tool.server else "Unknown",
                "host": req.host,
                "port": req.port,
                "justification": req.justification,
                "requested_by": req.requested_by,
                "status": req.status,
                "reviewed_by": req.reviewed_by,
                "reviewed_at": req.reviewed_at,
                "rejection_reason": req.rejection_reason,
                "created_at": req.created_at,
            }
            for req in requests
        ]

        return items, total

    async def get_network_access_requests_for_tool(
        self,
        tool_id: UUID,
    ) -> list[NetworkAccessRequest]:
        """Get all network access requests for a specific tool."""
        stmt = (
            select(NetworkAccessRequest)
            .where(NetworkAccessRequest.tool_id == tool_id)
            .order_by(NetworkAccessRequest.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # =========================================================================
    # Server-scoped Queries
    # =========================================================================

    async def get_module_requests_for_server(
        self,
        server_id: UUID,
        status: str | None = "approved",
    ) -> tuple[list[dict[str, Any]], int]:
        """Get module requests for all tools belonging to a server."""

        conditions = [Tool.server_id == server_id]
        if status and status != "all":
            conditions.append(ModuleRequest.status == status)

        count_stmt = (
            select(func.count(ModuleRequest.id))
            .select_from(ModuleRequest)
            .join(Tool, ModuleRequest.tool_id == Tool.id)
            .where(*conditions)
        )
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(ModuleRequest)
            .options(selectinload(ModuleRequest.tool).selectinload(Tool.server))
            .join(Tool, ModuleRequest.tool_id == Tool.id)
            .where(*conditions)
            .order_by(ModuleRequest.created_at.desc())
        )
        result = await self.db.execute(stmt)
        requests = result.scalars().all()

        items = [
            {
                "id": str(req.id),
                "tool_id": str(req.tool_id),
                "tool_name": req.tool.name if req.tool else "Unknown",
                "module_name": req.module_name,
                "justification": req.justification,
                "status": req.status,
                "reviewed_by": req.reviewed_by,
                "created_at": req.created_at.isoformat() if req.created_at else None,
            }
            for req in requests
        ]

        return items, total

    async def get_network_requests_for_server(
        self,
        server_id: UUID,
        status: str | None = "approved",
    ) -> tuple[list[dict[str, Any]], int]:
        """Get network access requests for all tools belonging to a server."""

        conditions = [Tool.server_id == server_id]
        if status and status != "all":
            conditions.append(NetworkAccessRequest.status == status)

        count_stmt = (
            select(func.count(NetworkAccessRequest.id))
            .select_from(NetworkAccessRequest)
            .join(Tool, NetworkAccessRequest.tool_id == Tool.id)
            .where(*conditions)
        )
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(NetworkAccessRequest)
            .options(selectinload(NetworkAccessRequest.tool).selectinload(Tool.server))
            .join(Tool, NetworkAccessRequest.tool_id == Tool.id)
            .where(*conditions)
            .order_by(NetworkAccessRequest.created_at.desc())
        )
        result = await self.db.execute(stmt)
        requests = result.scalars().all()

        items = [
            {
                "id": str(req.id),
                "tool_id": str(req.tool_id),
                "tool_name": req.tool.name if req.tool else "Unknown",
                "host": req.host,
                "port": req.port,
                "justification": req.justification,
                "status": req.status,
                "reviewed_by": req.reviewed_by,
                "created_at": req.created_at.isoformat() if req.created_at else None,
            }
            for req in requests
        ]

        return items, total

    # =========================================================================
    # Dashboard Statistics
    # =========================================================================

    async def get_dashboard_stats(self) -> dict[str, int]:
        """Get statistics for the approval dashboard.

        Returns:
            Dict with pending counts and recent activity counts
        """
        # Pending tools
        pending_tools_stmt = select(func.count(Tool.id)).where(
            Tool.approval_status == "pending_review"
        )
        pending_tools_result = await self.db.execute(pending_tools_stmt)
        pending_tools = pending_tools_result.scalar() or 0

        # Pending module requests
        pending_modules_stmt = select(func.count(ModuleRequest.id)).where(
            ModuleRequest.status == "pending"
        )
        pending_modules_result = await self.db.execute(pending_modules_stmt)
        pending_modules = pending_modules_result.scalar() or 0

        # Pending network requests
        pending_network_stmt = select(func.count(NetworkAccessRequest.id)).where(
            NetworkAccessRequest.status == "pending"
        )
        pending_network_result = await self.db.execute(pending_network_stmt)
        pending_network = pending_network_result.scalar() or 0

        # Approved tools (total)
        approved_tools_stmt = select(func.count(Tool.id)).where(Tool.approval_status == "approved")
        approved_tools_result = await self.db.execute(approved_tools_stmt)
        approved_tools = approved_tools_result.scalar() or 0

        # Approved module requests (total)
        approved_modules_stmt = select(func.count(ModuleRequest.id)).where(
            ModuleRequest.status == "approved"
        )
        approved_modules_result = await self.db.execute(approved_modules_stmt)
        approved_modules = approved_modules_result.scalar() or 0

        # Approved network access requests (total)
        approved_network_stmt = select(func.count(NetworkAccessRequest.id)).where(
            NetworkAccessRequest.status == "approved"
        )
        approved_network_result = await self.db.execute(approved_network_stmt)
        approved_network = approved_network_result.scalar() or 0

        # Recently approved (last 7 days)
        seven_days_ago = datetime.now(UTC) - timedelta(days=7)

        recently_approved_tools_stmt = select(func.count(Tool.id)).where(
            Tool.approval_status == "approved",
            Tool.approved_at >= seven_days_ago,
        )
        recently_approved_tools_result = await self.db.execute(recently_approved_tools_stmt)
        recently_approved = recently_approved_tools_result.scalar() or 0

        # Recently rejected (last 7 days)
        recently_rejected_stmt = select(func.count(Tool.id)).where(
            Tool.approval_status == "rejected",
            Tool.updated_at >= seven_days_ago,
        )
        recently_rejected_result = await self.db.execute(recently_rejected_stmt)
        recently_rejected = recently_rejected_result.scalar() or 0

        return {
            "pending_tools": pending_tools,
            "pending_module_requests": pending_modules,
            "pending_network_requests": pending_network,
            "approved_tools": approved_tools,
            "approved_module_requests": approved_modules,
            "approved_network_requests": approved_network,
            "recently_approved": recently_approved,
            "recently_rejected": recently_rejected,
        }

    # =========================================================================
    # Revocation
    # =========================================================================

    async def revoke_tool_approval(
        self,
        tool_id: UUID,
        revoked_by: str,
    ) -> Tool:
        """Revoke an approved tool back to pending_review status.

        The tool is removed from the live server registration and placed back
        into the approval queue so it can be reviewed again.

        Args:
            tool_id: ID of the tool to revoke
            revoked_by: Email of the admin revoking

        Returns:
            Updated tool (with server eagerly loaded for re-registration)

        Raises:
            ValueError: If tool not found or not currently approved
        """
        stmt = select(Tool).where(Tool.id == tool_id).options(selectinload(Tool.server))
        result = await self.db.execute(stmt)
        tool = result.scalar_one_or_none()

        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        if tool.approval_status != "approved":
            raise ValueError(
                f"Tool must be in 'approved' status to revoke. "
                f"Current status: {tool.approval_status}"
            )

        tool.approval_status = "pending_review"
        tool.approved_at = None
        tool.approved_by = None

        await self.db.commit()
        await self.db.refresh(tool, attribute_names=["server"])

        logger.info(f"Tool {tool.name} ({tool_id}) approval revoked by {revoked_by}")
        return tool

    async def revoke_module_request(
        self,
        request_id: UUID,
        revoked_by: str,
    ) -> ModuleRequest:
        """Revoke an approved module request back to pending status.

        The module is removed from the global allowed modules list so the
        sandbox will no longer permit it.

        Args:
            request_id: ID of the module request to revoke
            revoked_by: Email of the admin revoking

        Returns:
            Updated module request

        Raises:
            ValueError: If request not found or not currently approved
        """
        stmt = (
            select(ModuleRequest)
            .options(selectinload(ModuleRequest.tool).selectinload(Tool.server))
            .where(ModuleRequest.id == request_id)
        )
        result = await self.db.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            raise ValueError(f"Module request {request_id} not found")

        if request.status != "approved":
            raise ValueError(
                f"Module request must be in 'approved' status to revoke. "
                f"Current status: {request.status}"
            )

        request.status = "pending"
        request.reviewed_at = None
        request.reviewed_by = None
        request.rejection_reason = None

        # Remove module from global allowed modules list
        from app.services.global_config import GlobalConfigService

        config_service = GlobalConfigService(self.db)
        await config_service.remove_module(request.module_name)

        await self.db.commit()
        await self.db.refresh(request)

        logger.info(f"Module request {request_id} ({request.module_name}) revoked by {revoked_by}")
        return request

    async def revoke_network_access_request(
        self,
        request_id: UUID,
        revoked_by: str,
    ) -> NetworkAccessRequest:
        """Revoke an approved network access request back to pending status.

        The host is removed from the server's allowed hosts list.

        Args:
            request_id: ID of the network request to revoke
            revoked_by: Email of the admin revoking

        Returns:
            Updated network access request

        Raises:
            ValueError: If request not found or not currently approved
        """
        stmt = (
            select(NetworkAccessRequest)
            .options(selectinload(NetworkAccessRequest.tool).selectinload(Tool.server))
            .where(NetworkAccessRequest.id == request_id)
        )
        result = await self.db.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            raise ValueError(f"Network access request {request_id} not found")

        if request.status != "approved":
            raise ValueError(
                f"Network access request must be in 'approved' status to revoke. "
                f"Current status: {request.status}"
            )

        request.status = "pending"
        request.reviewed_at = None
        request.reviewed_by = None
        request.rejection_reason = None

        # Remove host from server's allowed hosts list
        server = request.tool.server
        if server and server.allowed_hosts:
            updated_hosts = [h for h in server.allowed_hosts if h != request.host]
            server.allowed_hosts = updated_hosts

        await self.db.commit()
        await self.db.refresh(request)

        logger.info(f"Network access request {request_id} ({request.host}) revoked by {revoked_by}")
        return request

    # =========================================================================
    # Bulk Actions
    # =========================================================================

    async def bulk_approve_tools(
        self,
        tool_ids: list[UUID],
        approved_by: str,
    ) -> dict:
        """Approve multiple tools at once.

        Args:
            tool_ids: List of tool IDs to approve
            approved_by: Email of the admin approving

        Returns:
            Dict with processed_count and failed list
        """
        processed = 0
        failed = []

        for tool_id in tool_ids:
            try:
                await self.approve_tool(tool_id, approved_by)
                processed += 1
            except ValueError as e:
                failed.append({"id": tool_id, "error": str(e)})

        return {
            "success": len(failed) == 0,
            "processed_count": processed,
            "failed": failed,
        }

    async def bulk_reject_tools(
        self,
        tool_ids: list[UUID],
        rejected_by: str,
        reason: str,
    ) -> dict:
        """Reject multiple tools at once.

        Args:
            tool_ids: List of tool IDs to reject
            rejected_by: Email of the admin rejecting
            reason: Reason for rejection

        Returns:
            Dict with processed_count and failed list
        """
        processed = 0
        failed = []

        for tool_id in tool_ids:
            try:
                await self.reject_tool(tool_id, rejected_by, reason)
                processed += 1
            except ValueError as e:
                failed.append({"id": tool_id, "error": str(e)})

        return {
            "success": len(failed) == 0,
            "processed_count": processed,
            "failed": failed,
        }

    async def bulk_approve_module_requests(
        self,
        request_ids: list[UUID],
        approved_by: str,
    ) -> dict:
        """Approve multiple module requests at once.

        Args:
            request_ids: List of request IDs to approve
            approved_by: Email of the admin approving

        Returns:
            Dict with processed_count and failed list
        """
        processed = 0
        failed = []

        for request_id in request_ids:
            try:
                await self.approve_module_request(request_id, approved_by)
                processed += 1
            except ValueError as e:
                failed.append({"id": request_id, "error": str(e)})

        return {
            "success": len(failed) == 0,
            "processed_count": processed,
            "failed": failed,
        }

    async def bulk_reject_module_requests(
        self,
        request_ids: list[UUID],
        rejected_by: str,
        reason: str,
    ) -> dict:
        """Reject multiple module requests at once.

        Args:
            request_ids: List of request IDs to reject
            rejected_by: Email of the admin rejecting
            reason: Reason for rejection

        Returns:
            Dict with processed_count and failed list
        """
        processed = 0
        failed = []

        for request_id in request_ids:
            try:
                await self.reject_module_request(request_id, rejected_by, reason)
                processed += 1
            except ValueError as e:
                failed.append({"id": request_id, "error": str(e)})

        return {
            "success": len(failed) == 0,
            "processed_count": processed,
            "failed": failed,
        }

    async def bulk_approve_network_requests(
        self,
        request_ids: list[UUID],
        approved_by: str,
    ) -> dict:
        """Approve multiple network access requests at once.

        Args:
            request_ids: List of request IDs to approve
            approved_by: Email of the admin approving

        Returns:
            Dict with processed_count and failed list
        """
        processed = 0
        failed = []

        for request_id in request_ids:
            try:
                await self.approve_network_access_request(request_id, approved_by)
                processed += 1
            except ValueError as e:
                failed.append({"id": request_id, "error": str(e)})

        return {
            "success": len(failed) == 0,
            "processed_count": processed,
            "failed": failed,
        }

    async def bulk_reject_network_requests(
        self,
        request_ids: list[UUID],
        rejected_by: str,
        reason: str,
    ) -> dict:
        """Reject multiple network access requests at once.

        Args:
            request_ids: List of request IDs to reject
            rejected_by: Email of the admin rejecting
            reason: Reason for rejection

        Returns:
            Dict with processed_count and failed list
        """
        processed = 0
        failed = []

        for request_id in request_ids:
            try:
                await self.reject_network_access_request(request_id, rejected_by, reason)
                processed += 1
            except ValueError as e:
                failed.append({"id": request_id, "error": str(e)})

        return {
            "success": len(failed) == 0,
            "processed_count": processed,
            "failed": failed,
        }
