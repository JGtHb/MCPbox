"""Pydantic schemas for approval workflow, module requests, and network access requests."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# Tool Approval Schemas
# ============================================================================


class ToolApprovalRequest(BaseModel):
    """Schema for requesting tool approval."""

    notes: str | None = Field(
        None,
        max_length=2000,
        description="Notes for the reviewer explaining what this tool does",
    )


class ToolApprovalAction(BaseModel):
    """Schema for admin approval/rejection action."""

    action: str = Field(..., pattern="^(approve|reject|submit_for_review)$")
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Required for rejection, optional for approval/submit",
    )


class ToolApprovalQueueItem(BaseModel):
    """Schema for tools in the approval queue."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    server_id: UUID
    server_name: str
    name: str
    description: str | None
    python_code: str | None
    created_by: str | None
    publish_notes: str | None
    approval_status: str | None = None
    approval_requested_at: datetime | None
    approved_at: datetime | None = None
    approved_by: str | None = None
    rejection_reason: str | None = None
    current_version: int


class ToolApprovalQueueResponse(BaseModel):
    """Schema for paginated approval queue response."""

    items: list[ToolApprovalQueueItem]
    total: int
    page: int
    page_size: int
    pages: int


# ============================================================================
# Module Request Schemas
# ============================================================================


class ModuleRequestCreate(BaseModel):
    """Schema for creating a module whitelist request."""

    tool_id: UUID
    module_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the Python module to whitelist (e.g., 'xml.etree.ElementTree')",
    )
    justification: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Explanation of why this module is needed",
    )


class ModuleRequestResponse(BaseModel):
    """Schema for module request response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_id: UUID | None
    server_id: UUID | None = None
    module_name: str
    justification: str
    requested_by: str | None
    status: str
    reviewed_at: datetime | None
    reviewed_by: str | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class VulnerabilityInfo(BaseModel):
    """A known vulnerability from OSV.dev."""

    id: str  # e.g., "GHSA-xxxx" or "CVE-2024-xxxx"
    summary: str
    severity: str | None = None  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    fixed_version: str | None = None
    link: str | None = None


class PyPIPackageInfo(BaseModel):
    """PyPI package information and safety data for module requests."""

    package_name: str
    is_stdlib: bool
    is_installed: bool = False
    installed_version: str | None = None
    latest_version: str | None = None
    summary: str | None = None
    author: str | None = None
    license: str | None = None
    home_page: str | None = None
    # Safety data from external sources (OSV.dev, deps.dev)
    vulnerabilities: list[VulnerabilityInfo] = []
    vulnerability_count: int = 0
    scorecard_score: float | None = None  # OpenSSF Scorecard overall score (0-10)
    scorecard_date: str | None = None
    dependency_count: int | None = None
    source_repo: str | None = None
    error: str | None = None


class ModuleRequestQueueItem(BaseModel):
    """Schema for module requests in the admin queue."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_id: UUID | None
    tool_name: str | None
    server_id: UUID | None
    server_name: str | None
    module_name: str
    justification: str
    requested_by: str | None
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    source: str = "llm"  # "llm" or "admin"
    # PyPI info (populated separately, not from DB)
    pypi_info: PyPIPackageInfo | None = None


class ModuleRequestQueueResponse(BaseModel):
    """Schema for paginated module request queue response."""

    items: list[ModuleRequestQueueItem]
    total: int
    page: int
    page_size: int
    pages: int


class ModuleRequestAction(BaseModel):
    """Schema for admin action on module request."""

    action: str = Field(..., pattern="^(approve|reject)$")
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Required for rejection, optional for approval",
    )


# ============================================================================
# Network Access Request Schemas
# ============================================================================


class NetworkAccessRequestCreate(BaseModel):
    """Schema for creating a network access request."""

    tool_id: UUID
    host: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Hostname or IP address to whitelist (e.g., 'api.github.com')",
    )
    port: int | None = Field(
        None,
        ge=1,
        le=65535,
        description="Optional port number (defaults to any port if not specified)",
    )
    justification: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Explanation of why this network access is needed",
    )


class NetworkAccessRequestResponse(BaseModel):
    """Schema for network access request response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_id: UUID | None
    server_id: UUID | None = None
    host: str
    port: int | None
    justification: str
    requested_by: str | None
    status: str
    reviewed_at: datetime | None
    reviewed_by: str | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class NetworkAccessRequestQueueItem(BaseModel):
    """Schema for network access requests in the admin queue."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_id: UUID | None
    tool_name: str | None
    server_id: UUID | None
    server_name: str | None
    host: str
    port: int | None
    justification: str
    requested_by: str | None
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    source: str = "llm"  # "llm" or "admin"


class NetworkAccessRequestQueueResponse(BaseModel):
    """Schema for paginated network access request queue response."""

    items: list[NetworkAccessRequestQueueItem]
    total: int
    page: int
    page_size: int
    pages: int


class NetworkAccessRequestAction(BaseModel):
    """Schema for admin action on network access request."""

    action: str = Field(..., pattern="^(approve|reject)$")
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Required for rejection, optional for approval",
    )


# ============================================================================
# Bulk Action Schemas
# ============================================================================


class BulkToolAction(BaseModel):
    """Schema for bulk tool approval/rejection action."""

    tool_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    action: str = Field(..., pattern="^(approve|reject)$")
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Required for rejection, optional for approval",
    )


class BulkModuleRequestAction(BaseModel):
    """Schema for bulk module request approval/rejection action."""

    request_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    action: str = Field(..., pattern="^(approve|reject)$")
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Required for rejection, optional for approval",
    )


class BulkNetworkRequestAction(BaseModel):
    """Schema for bulk network request approval/rejection action."""

    request_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    action: str = Field(..., pattern="^(approve|reject)$")
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Required for rejection, optional for approval",
    )


class BulkActionFailure(BaseModel):
    """Schema for a failed item in a bulk action."""

    id: UUID
    error: str


class BulkActionResponse(BaseModel):
    """Schema for bulk action response."""

    success: bool
    processed_count: int
    failed: list[BulkActionFailure] = []


# ============================================================================
# Combined Approval Dashboard Schemas
# ============================================================================


class ApprovalDashboardStats(BaseModel):
    """Statistics for the approval dashboard."""

    pending_tools: int
    pending_module_requests: int
    pending_network_requests: int
    approved_tools: int
    approved_module_requests: int
    approved_network_requests: int
    recently_approved: int
    recently_rejected: int
