"""Shared utility functions for tool operations."""

from typing import Any


def build_tool_definitions(
    tools: list,
    *,
    filter_enabled_approved: bool = False,
) -> list[dict[str, Any]]:
    """Build tool definitions for sandbox registration.

    Converts Tool model instances to dicts suitable for the sandbox API.
    Handles both python_code and mcp_passthrough tools.

    Args:
        tools: List of Tool model instances.
        filter_enabled_approved: If True, only include tools that are
            enabled and have approval_status == "approved".

    Returns:
        List of tool definition dicts.
    """
    tool_defs = []

    for tool in tools:
        if filter_enabled_approved:
            if not tool.enabled:
                continue
            if tool.approval_status != "approved":
                continue

        tool_def = {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema or {},
            "python_code": tool.python_code,
            "timeout_ms": tool.timeout_ms or 30000,
            "tool_type": getattr(tool, "tool_type", "python_code"),
        }

        # Add passthrough-specific fields
        if tool_def["tool_type"] == "mcp_passthrough":
            tool_def["external_source_id"] = (
                str(tool.external_source_id) if tool.external_source_id else None
            )
            tool_def["external_tool_name"] = tool.external_tool_name

        tool_defs.append(tool_def)

    return tool_defs
