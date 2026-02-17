"""Pydantic schemas for Tool API."""

import ast
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApprovalStatus(StrEnum):
    """Approval status for a tool."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolBase(BaseModel):
    """Base schema for tool data."""

    name: str = Field(..., min_length=1, max_length=255, pattern="^[a-z][a-z0-9_]*$")
    description: str | None = Field(None, max_length=2000)


class ToolCreate(ToolBase):
    """Schema for creating a new tool.

    Tools use Python code with an async main() function for execution.
    """

    python_code: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="Python code with async main() function",
    )
    code_dependencies: list[str] | None = Field(
        None,
        max_length=20,
        description="Pip packages required by the Python code",
    )
    timeout_ms: int | None = Field(
        None,
        ge=1000,
        le=300000,
        description="Tool execution timeout in milliseconds (1s-5min). If not set, inherits from server.",
    )

    @model_validator(mode="after")
    def validate_python_code_syntax(self) -> "ToolCreate":
        """Validate Python code syntax."""
        validation_result = validate_python_code(self.python_code)
        if not validation_result["valid"]:
            raise ValueError(f"Invalid Python code: {validation_result['error']}")
        if not validation_result["has_main"]:
            raise ValueError("Python code must contain an async main() function")
        return self


class ToolUpdate(BaseModel):
    """Schema for updating a tool."""

    name: str | None = Field(None, min_length=1, max_length=255, pattern="^[a-z][a-z0-9_]*$")
    description: str | None = Field(None, max_length=2000)
    enabled: bool | None = None
    timeout_ms: int | None = Field(None, ge=1000, le=300000)
    python_code: str | None = Field(None, max_length=100000)
    code_dependencies: list[str] | None = Field(None, max_length=20)

    @model_validator(mode="after")
    def validate_python_code_if_provided(self) -> "ToolUpdate":
        """Validate Python code syntax if provided."""
        if self.python_code is not None:
            validation_result = validate_python_code(self.python_code)
            if not validation_result["valid"]:
                raise ValueError(f"Invalid Python code: {validation_result['error']}")
            if not validation_result["has_main"]:
                raise ValueError("Python code must contain an async main() function")
        return self


class ToolResponse(BaseModel):
    """Schema for tool response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    server_id: UUID
    name: str
    description: str | None
    enabled: bool
    timeout_ms: int | None
    python_code: str | None
    code_dependencies: list[str] | None
    input_schema: dict[str, Any] | None
    current_version: int = 1
    # Tool type
    tool_type: str = "python_code"
    external_source_id: UUID | None = None
    external_tool_name: str | None = None
    # Approval workflow fields
    approval_status: str = "draft"
    approval_requested_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    rejection_reason: str | None = None
    created_by: str | None = None
    publish_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ToolVersionResponse(BaseModel):
    """Schema for tool version response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tool_id: UUID
    version_number: int
    name: str
    description: str | None
    enabled: bool
    timeout_ms: int | None
    python_code: str | None
    input_schema: dict[str, Any] | None
    change_summary: str | None
    change_source: str
    created_at: datetime


class ToolVersionListResponse(BaseModel):
    """Schema for listing tool versions."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    change_summary: str | None
    change_source: str
    created_at: datetime


class ToolVersionDiff(BaseModel):
    """Schema for showing differences between versions."""

    field: str
    old_value: Any | None
    new_value: Any | None


class ToolVersionCompare(BaseModel):
    """Schema for version comparison response."""

    from_version: int
    to_version: int
    differences: list[ToolVersionDiff]


class ToolListResponse(BaseModel):
    """Schema for tool list response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    enabled: bool
    tool_type: str = "python_code"
    external_tool_name: str | None = None
    approval_status: str = "draft"
    created_by: str | None = None


class ToolListPaginatedResponse(BaseModel):
    """Schema for paginated tool list response."""

    items: list[ToolListResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ToolVersionListPaginatedResponse(BaseModel):
    """Schema for paginated tool version list response."""

    items: list[ToolVersionListResponse]
    total: int
    page: int
    page_size: int
    pages: int


def validate_python_code(code: str) -> dict[str, Any]:
    """Validate Python code syntax and check for required main() function.

    Returns a dict with:
    - valid: bool - whether the code is syntactically valid
    - has_main: bool - whether the code contains an async main() function
    - error: Optional[str] - error message if invalid
    - parameters: list[dict] - extracted parameters from main() signature
    """
    result: dict[str, Any] = {
        "valid": False,
        "has_main": False,
        "error": None,
        "parameters": [],
    }

    # Check for empty code
    if not code or not code.strip():
        result["error"] = "Code cannot be empty"
        return result

    # Try to parse the code
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        result["error"] = f"Syntax error at line {e.lineno}: {e.msg}"
        return result

    result["valid"] = True

    # Look for async def main(...) function
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main":
            result["has_main"] = True

            # Extract parameters from main() signature
            for arg in node.args.args:
                param = {
                    "name": arg.arg,
                    "type": None,
                }
                # Try to get type annotation
                if arg.annotation:
                    try:
                        param["type"] = ast.unparse(arg.annotation)
                    except Exception:
                        pass
                result["parameters"].append(param)
            break

    return result


def extract_input_schema_from_python(code: str) -> dict[str, Any]:
    """Extract MCP input schema from Python code main() function signature.

    Analyzes the async main() function parameters and their type annotations
    to generate a JSON Schema for the tool's input.
    """
    validation_result = validate_python_code(code)

    if not validation_result["valid"] or not validation_result["has_main"]:
        return {"type": "object", "properties": {}}

    properties = {}
    required = []

    # Map Python type hints to JSON Schema types
    type_mapping = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
        "List": "array",
        "Dict": "object",
        "Optional": None,  # Will be handled specially
    }

    for param in validation_result["parameters"]:
        param_name = param["name"]
        param_type = param["type"]

        # Skip self, cls, and injected parameters
        if param_name in ("self", "cls", "http"):
            continue

        prop = {"description": f"Parameter: {param_name}"}

        # Determine JSON schema type from Python type
        if param_type:
            # Handle Optional[X] - not required
            is_optional = param_type.startswith("Optional[") or " | None" in param_type

            # Extract base type
            base_type = param_type
            if is_optional:
                if param_type.startswith("Optional["):
                    base_type = param_type[9:-1]  # Remove Optional[...]
                else:
                    base_type = param_type.replace(" | None", "").strip()

            json_type = type_mapping.get(base_type, "string")
            if json_type:
                prop["type"] = json_type
            else:
                prop["type"] = "string"

            if not is_optional:
                required.append(param_name)
        else:
            # No type annotation, assume string and required
            prop["type"] = "string"
            required.append(param_name)

        properties[param_name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required if required else None,
    }
