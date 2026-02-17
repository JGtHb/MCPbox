"""Unit tests for ToolService business logic."""

from uuid import uuid4

import pytest

from app.schemas.tool import ToolCreate, ToolUpdate
from app.services.tool import ToolService

pytestmark = pytest.mark.asyncio


class TestToolServiceCreate:
    """Tests for ToolService.create()."""

    async def test_create_python_code_tool(self, db_session, server_factory):
        """Create a tool with Python code."""
        server = await server_factory()
        service = ToolService(db_session)

        code = '''
async def main(name: str, count: int = 10) -> dict:
    """Greet the user."""
    return {"message": f"Hello {name}!", "count": count}
'''
        data = ToolCreate(
            name="greet",
            description="Greet a user",
            python_code=code,
        )

        tool = await service.create(server.id, data)

        assert tool.name == "greet"
        assert tool.description == "Greet a user"
        assert tool.python_code == code
        assert tool.enabled is True
        assert tool.current_version == 1
        # Input schema should be extracted from function signature
        assert "name" in tool.input_schema.get("properties", {})
        assert "count" in tool.input_schema.get("properties", {})

    async def test_create_tool_creates_initial_version(self, db_session, server_factory):
        """Creating a tool should create an initial version entry."""
        server = await server_factory()
        service = ToolService(db_session)

        code = """
async def main() -> dict:
    return {"status": "ok"}
"""
        data = ToolCreate(
            name="test_tool",
            description="A test tool",
            python_code=code,
        )

        tool = await service.create(server.id, data)

        # Check version was created
        versions, total = await service.list_versions(tool.id)
        assert total == 1
        assert versions[0].version_number == 1
        assert versions[0].change_summary == "Initial version"
        assert versions[0].change_source == "manual"

    async def test_create_tool_custom_change_source(self, db_session, server_factory):
        """Create a tool with custom change source."""
        server = await server_factory()
        service = ToolService(db_session)

        code = """
async def main() -> dict:
    return {}
"""
        data = ToolCreate(
            name="imported_tool",
            description="Imported tool",
            python_code=code,
        )

        tool = await service.create(server.id, data, change_source="mcp_management")

        versions, _ = await service.list_versions(tool.id)
        assert versions[0].change_source == "mcp_management"


class TestToolServiceUpdate:
    """Tests for ToolService.update()."""

    async def test_update_description(self, db_session, tool_factory):
        """Update tool description creates new version."""
        tool = await tool_factory(name="original", description="Original desc")
        service = ToolService(db_session)

        updated = await service.update(
            tool.id,
            ToolUpdate(description="Updated description"),
        )

        assert updated.description == "Updated description"
        assert updated.current_version == 2

        # Check version history
        versions, _ = await service.list_versions(tool.id)
        assert len(versions) == 2
        assert versions[0].version_number == 2  # Newest first

    async def test_update_no_changes_skips_version(self, db_session, tool_factory):
        """Update with no actual changes doesn't create version."""
        tool = await tool_factory(name="test", description="Original")
        service = ToolService(db_session)

        # Update with same values
        updated = await service.update(
            tool.id,
            ToolUpdate(description="Original"),  # Same as current
        )

        assert updated.current_version == 1  # No version bump
        versions, total = await service.list_versions(tool.id)
        assert total == 1

    async def test_update_python_code_regenerates_schema(self, db_session, tool_factory):
        """Updating python_code regenerates input_schema."""
        tool = await tool_factory(
            python_code="async def main(old_param: str) -> dict:\n    return {}",
        )
        service = ToolService(db_session)

        updated = await service.update(
            tool.id,
            ToolUpdate(
                python_code="async def main(new_param: int) -> dict:\n    return {}",
            ),
        )

        # Schema should reflect new param, not old
        assert "new_param" in updated.input_schema.get("properties", {})

    async def test_update_generates_change_summary(self, db_session, tool_factory):
        """Update auto-generates human-readable change summary."""
        tool = await tool_factory()
        service = ToolService(db_session)

        await service.update(
            tool.id,
            ToolUpdate(name="new_name", description="new desc"),
        )

        versions, _ = await service.list_versions(tool.id)
        latest = versions[0]
        assert "name" in latest.change_summary
        assert "description" in latest.change_summary

    async def test_update_nonexistent_tool_returns_none(self, db_session):
        """Update on non-existent tool returns None."""
        service = ToolService(db_session)

        result = await service.update(
            uuid4(),
            ToolUpdate(description="test"),
        )

        assert result is None


class TestToolServiceDelete:
    """Tests for ToolService.delete()."""

    async def test_delete_existing_tool(self, db_session, tool_factory):
        """Delete an existing tool."""
        tool = await tool_factory()
        tool_id = tool.id
        service = ToolService(db_session)

        result = await service.delete(tool_id)

        assert result is True
        assert await service.get(tool_id) is None

    async def test_delete_nonexistent_tool(self, db_session):
        """Delete non-existent tool returns False."""
        service = ToolService(db_session)

        result = await service.delete(uuid4())

        assert result is False


class TestToolServiceToggle:
    """Tests for ToolService.toggle_enabled()."""

    async def test_toggle_enabled_to_disabled(self, db_session, tool_factory):
        """Disable an enabled tool."""
        tool = await tool_factory(enabled=True)
        service = ToolService(db_session)

        updated = await service.toggle_enabled(tool.id, False)

        assert updated.enabled is False

    async def test_toggle_disabled_to_enabled(self, db_session, tool_factory):
        """Enable a disabled tool."""
        tool = await tool_factory(enabled=False)
        service = ToolService(db_session)

        updated = await service.toggle_enabled(tool.id, True)

        assert updated.enabled is True

    async def test_toggle_nonexistent_returns_none(self, db_session):
        """Toggle non-existent tool returns None."""
        service = ToolService(db_session)

        result = await service.toggle_enabled(uuid4(), True)

        assert result is None


class TestToolServiceVersions:
    """Tests for version management methods."""

    async def test_list_versions_pagination(self, db_session, tool_factory):
        """List versions respects pagination."""
        tool = await tool_factory()
        service = ToolService(db_session)

        # Create multiple versions
        for i in range(5):
            await service.update(tool.id, ToolUpdate(description=f"Version {i + 2}"))

        # Total should be 6 (initial + 5 updates)
        versions, total = await service.list_versions(tool.id, page=1, page_size=3)
        assert total == 6
        assert len(versions) == 3
        # Newest first
        assert versions[0].version_number == 6

        # Second page
        versions2, _ = await service.list_versions(tool.id, page=2, page_size=3)
        assert len(versions2) == 3
        assert versions2[0].version_number == 3

    async def test_get_specific_version(self, db_session, tool_factory):
        """Get a specific version by number."""
        tool = await tool_factory()
        service = ToolService(db_session)

        await service.update(tool.id, ToolUpdate(description="v2"))
        await service.update(tool.id, ToolUpdate(description="v3"))

        version = await service.get_version(tool.id, 2)

        assert version is not None
        assert version.version_number == 2
        assert version.description == "v2"

    async def test_get_nonexistent_version(self, db_session, tool_factory):
        """Get non-existent version returns None."""
        tool = await tool_factory()
        service = ToolService(db_session)

        version = await service.get_version(tool.id, 999)

        assert version is None


class TestToolServiceRollback:
    """Tests for ToolService.rollback()."""

    async def test_rollback_to_previous_version(self, db_session, tool_factory):
        """Rollback restores previous state and creates new version."""
        tool = await tool_factory(name="original", description="v1 desc")
        service = ToolService(db_session)

        # Make changes
        await service.update(tool.id, ToolUpdate(name="changed", description="v2 desc"))
        await service.update(tool.id, ToolUpdate(description="v3 desc"))

        # Rollback to version 1
        rolled_back = await service.rollback(tool.id, 1)

        assert rolled_back.name == "original"
        assert rolled_back.description == "v1 desc"
        assert rolled_back.current_version == 4  # New version created

        # Check rollback version entry
        versions, _ = await service.list_versions(tool.id)
        assert versions[0].change_summary == "Rolled back to version 1"
        assert versions[0].change_source == "rollback"

    async def test_rollback_nonexistent_tool(self, db_session):
        """Rollback non-existent tool returns None."""
        service = ToolService(db_session)

        result = await service.rollback(uuid4(), 1)

        assert result is None

    async def test_rollback_nonexistent_version(self, db_session, tool_factory):
        """Rollback to non-existent version returns None."""
        tool = await tool_factory()
        service = ToolService(db_session)

        result = await service.rollback(tool.id, 999)

        assert result is None


class TestToolServiceCompare:
    """Tests for version comparison."""

    async def test_compare_versions_detects_changes(self, db_session, tool_factory):
        """Compare versions returns list of differences."""
        tool = await tool_factory(name="v1", description="desc1")
        service = ToolService(db_session)

        await service.update(tool.id, ToolUpdate(name="v2", description="desc2"))

        v1 = await service.get_version(tool.id, 1)
        v2 = await service.get_version(tool.id, 2)

        diffs = service.compare_versions(v1, v2)

        field_names = [d.field for d in diffs]
        assert "name" in field_names
        assert "description" in field_names

        name_diff = next(d for d in diffs if d.field == "name")
        assert name_diff.old_value == "v1"
        assert name_diff.new_value == "v2"

    async def test_compare_identical_versions(self, db_session, tool_factory):
        """Compare identical versions returns empty list."""
        tool = await tool_factory()
        service = ToolService(db_session)

        v1 = await service.get_version(tool.id, 1)

        diffs = service.compare_versions(v1, v1)

        assert diffs == []


class TestToolServiceApprovalSecurity:
    """Tests for approval status security (SEC-001, SEC-002)."""

    async def test_update_python_code_resets_approval(self, db_session, tool_factory):
        """SEC-001: Updating python_code resets approval_status to pending_review."""
        tool = await tool_factory(
            approval_status="approved",
            python_code='async def main() -> str:\n    return "v1"',
        )
        assert tool.approval_status == "approved"

        service = ToolService(db_session)
        updated = await service.update(
            tool.id,
            ToolUpdate(python_code='async def main() -> str:\n    return "v2"'),
        )

        assert updated.approval_status == "pending_review"

    async def test_update_non_code_field_preserves_approval(self, db_session, tool_factory):
        """Updating name/description does NOT reset approval_status."""
        tool = await tool_factory(approval_status="approved")
        service = ToolService(db_session)

        updated = await service.update(
            tool.id,
            ToolUpdate(name="renamed_tool", description="new desc"),
        )

        assert updated.approval_status == "approved"

    async def test_update_identical_code_preserves_approval(self, db_session, tool_factory):
        """Re-submitting identical python_code does NOT reset approval."""
        code = 'async def main() -> str:\n    return "same"'
        tool = await tool_factory(approval_status="approved", python_code=code)
        service = ToolService(db_session)

        updated = await service.update(
            tool.id,
            ToolUpdate(python_code=code),
        )

        # No actual change — should skip versioning entirely
        assert updated.approval_status == "approved"

    async def test_rollback_resets_approval(self, db_session, tool_factory):
        """SEC-002: Rollback always resets approval_status to pending_review."""
        tool = await tool_factory(
            approval_status="approved",
            name="original",
            python_code='async def main() -> str:\n    return "v1"',
        )
        service = ToolService(db_session)

        # Create v2
        await service.update(
            tool.id,
            ToolUpdate(python_code='async def main() -> str:\n    return "v2"'),
        )

        # Approve v2 manually (simulate admin approval)
        tool.approval_status = "approved"
        await db_session.flush()

        # Rollback to v1
        rolled_back = await service.rollback(tool.id, 1)

        assert rolled_back.approval_status == "pending_review"
        assert rolled_back.name == "original"


class TestToolServiceList:
    """Tests for listing tools."""

    async def test_list_by_server(self, db_session, server_factory, tool_factory):
        """List tools for a specific server."""
        server1 = await server_factory(name="Server 1")
        server2 = await server_factory(name="Server 2")

        await tool_factory(server=server1, name="tool1")
        await tool_factory(server=server1, name="tool2")
        await tool_factory(server=server2, name="tool3")

        service = ToolService(db_session)
        tools, total = await service.list_by_server(server1.id)

        assert total == 2
        assert len(tools) == 2
        assert all(t.server_id == server1.id for t in tools)

    async def test_list_by_server_pagination(self, db_session, server_factory, tool_factory):
        """List respects pagination parameters."""
        server = await server_factory()
        for i in range(10):
            await tool_factory(server=server, name=f"tool{i}")

        service = ToolService(db_session)

        # First page
        tools, total = await service.list_by_server(server.id, page=1, page_size=3)
        assert total == 10
        assert len(tools) == 3

        # Last page
        tools, total = await service.list_by_server(server.id, page=4, page_size=3)
        assert len(tools) == 1
