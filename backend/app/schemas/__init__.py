# MCPbox Pydantic Schemas
from app.schemas.approval import (
    ApprovalDashboardStats,
    ModuleRequestAction,
    ModuleRequestCreate,
    ModuleRequestQueueItem,
    ModuleRequestQueueResponse,
    ModuleRequestResponse,
    NetworkAccessRequestAction,
    NetworkAccessRequestCreate,
    NetworkAccessRequestQueueItem,
    NetworkAccessRequestQueueResponse,
    NetworkAccessRequestResponse,
    ToolApprovalAction,
    ToolApprovalQueueItem,
    ToolApprovalQueueResponse,
    ToolApprovalRequest,
)
from app.schemas.server import (
    ServerCreate,
    ServerListResponse,
    ServerResponse,
    ServerUpdate,
)
from app.schemas.tool import (
    ApprovalStatus,
    ToolCreate,
    ToolListResponse,
    ToolResponse,
    ToolUpdate,
)
from app.schemas.tunnel_configuration import (
    TunnelConfigurationCreate,
    TunnelConfigurationListPaginatedResponse,
    TunnelConfigurationListResponse,
    TunnelConfigurationResponse,
    TunnelConfigurationUpdate,
)

__all__ = [
    # Approval
    "ApprovalDashboardStats",
    "ApprovalStatus",
    "ModuleRequestAction",
    "ModuleRequestCreate",
    "ModuleRequestQueueItem",
    "ModuleRequestQueueResponse",
    "ModuleRequestResponse",
    "NetworkAccessRequestAction",
    "NetworkAccessRequestCreate",
    "NetworkAccessRequestQueueItem",
    "NetworkAccessRequestQueueResponse",
    "NetworkAccessRequestResponse",
    "ToolApprovalAction",
    "ToolApprovalQueueItem",
    "ToolApprovalQueueResponse",
    "ToolApprovalRequest",
    # Server
    "ServerCreate",
    "ServerListResponse",
    "ServerResponse",
    "ServerUpdate",
    # Tool
    "ToolCreate",
    "ToolListResponse",
    "ToolResponse",
    "ToolUpdate",
    # Tunnel
    "TunnelConfigurationCreate",
    "TunnelConfigurationListPaginatedResponse",
    "TunnelConfigurationListResponse",
    "TunnelConfigurationResponse",
    "TunnelConfigurationUpdate",
]
