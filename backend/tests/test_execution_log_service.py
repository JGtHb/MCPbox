"""Unit tests for ExecutionLogService business logic."""

from uuid import uuid4

from app.services.execution_log import ExecutionLogService


class TestCreateLog:
    """Tests for ExecutionLogService.create_log()."""

    async def test_create_log(self, db_session, server_factory, tool_factory):
        """Verify log created with correct fields."""
        server = await server_factory()
        tool = await tool_factory(server=server, name="my_tool")

        service = ExecutionLogService(db_session)
        log = await service.create_log(
            tool_id=tool.id,
            server_id=server.id,
            tool_name="my_tool",
            input_args={"query": "hello"},
            result={"output": "world"},
            error=None,
            stdout="some output",
            duration_ms=150,
            success=True,
            executed_by="testuser@example.com",
        )

        assert log.id is not None
        assert log.tool_id == tool.id
        assert log.server_id == server.id
        assert log.tool_name == "my_tool"
        assert log.input_args == {"query": "hello"}
        assert log.result == {"output": "world"}
        assert log.error is None
        assert log.stdout == "some output"
        assert log.duration_ms == 150
        assert log.success is True
        assert log.executed_by == "testuser@example.com"

    async def test_create_log_redacts_sensitive_args(
        self, db_session, server_factory, tool_factory
    ):
        """Pass args with sensitive keys, verify password is redacted."""
        server = await server_factory()
        tool = await tool_factory(server=server)

        service = ExecutionLogService(db_session)
        log = await service.create_log(
            tool_id=tool.id,
            server_id=server.id,
            tool_name="test_tool",
            input_args={"password": "secret123", "query": "safe"},
            result=None,
            success=True,
        )

        assert log.input_args["password"] == "[REDACTED]"
        assert log.input_args["query"] == "safe"

    async def test_create_log_truncates_long_result(self, db_session, server_factory, tool_factory):
        """Pass result > 10,000 chars, verify truncated."""
        server = await server_factory()
        tool = await tool_factory(server=server)

        # Create a result that serializes to > 10,000 chars
        long_result = {"data": "x" * 15_000}

        service = ExecutionLogService(db_session)
        log = await service.create_log(
            tool_id=tool.id,
            server_id=server.id,
            tool_name="test_tool",
            result=long_result,
            success=True,
        )

        assert log.result is not None
        assert log.result.get("_truncated") is True
        assert "_preview" in log.result
        assert len(log.result["_preview"]) <= 1100  # 1000 chars + "..."


class TestListByTool:
    """Tests for ExecutionLogService.list_by_tool()."""

    async def test_list_by_tool(self, db_session, server_factory, tool_factory):
        """Create multiple logs, verify filtering and order (newest first)."""
        server = await server_factory()
        tool = await tool_factory(server=server)

        service = ExecutionLogService(db_session)

        # Create 3 logs with slight delays to ensure ordering
        log1 = await service.create_log(
            tool_id=tool.id,
            server_id=server.id,
            tool_name="test_tool",
            input_args={"seq": 1},
            success=True,
        )
        await db_session.flush()

        log2 = await service.create_log(
            tool_id=tool.id,
            server_id=server.id,
            tool_name="test_tool",
            input_args={"seq": 2},
            success=True,
        )
        await db_session.flush()

        log3 = await service.create_log(
            tool_id=tool.id,
            server_id=server.id,
            tool_name="test_tool",
            input_args={"seq": 3},
            success=False,
        )
        await db_session.flush()

        logs, total = await service.list_by_tool(tool.id)

        assert total == 3
        assert len(logs) == 3
        # Newest first — log3 was created last
        assert logs[0].id == log3.id
        assert logs[1].id == log2.id
        assert logs[2].id == log1.id

    async def test_list_by_tool_filters_other_tools(self, db_session, server_factory, tool_factory):
        """Logs for a different tool should not appear."""
        server = await server_factory()
        tool_a = await tool_factory(server=server, name="tool_a")
        tool_b = await tool_factory(server=server, name="tool_b")

        service = ExecutionLogService(db_session)

        await service.create_log(
            tool_id=tool_a.id,
            server_id=server.id,
            tool_name="tool_a",
            success=True,
        )
        await service.create_log(
            tool_id=tool_b.id,
            server_id=server.id,
            tool_name="tool_b",
            success=True,
        )

        logs, total = await service.list_by_tool(tool_a.id)

        assert total == 1
        assert logs[0].tool_name == "tool_a"


class TestListByServer:
    """Tests for ExecutionLogService.list_by_server()."""

    async def test_list_by_server(self, db_session, server_factory, tool_factory):
        """Create logs for different tools on same server, list by server."""
        server = await server_factory()
        tool_a = await tool_factory(server=server, name="tool_a")
        tool_b = await tool_factory(server=server, name="tool_b")

        service = ExecutionLogService(db_session)

        await service.create_log(
            tool_id=tool_a.id,
            server_id=server.id,
            tool_name="tool_a",
            success=True,
        )
        await service.create_log(
            tool_id=tool_b.id,
            server_id=server.id,
            tool_name="tool_b",
            success=True,
        )

        logs, total = await service.list_by_server(server.id)

        assert total == 2
        assert len(logs) == 2
        # Both logs should belong to the same server
        assert all(log.server_id == server.id for log in logs)

    async def test_list_by_server_excludes_other_servers(
        self, db_session, server_factory, tool_factory
    ):
        """Logs for a different server should not appear."""
        server_1 = await server_factory(name="Server 1")
        server_2 = await server_factory(name="Server 2")
        tool_1 = await tool_factory(server=server_1, name="tool_1")
        tool_2 = await tool_factory(server=server_2, name="tool_2")

        service = ExecutionLogService(db_session)

        await service.create_log(
            tool_id=tool_1.id,
            server_id=server_1.id,
            tool_name="tool_1",
            success=True,
        )
        await service.create_log(
            tool_id=tool_2.id,
            server_id=server_2.id,
            tool_name="tool_2",
            success=True,
        )

        logs, total = await service.list_by_server(server_1.id)

        assert total == 1
        assert logs[0].tool_name == "tool_1"


class TestGetLog:
    """Tests for ExecutionLogService.get_log()."""

    async def test_get_log(self, db_session, server_factory, tool_factory):
        """Verify single log retrieval."""
        server = await server_factory()
        tool = await tool_factory(server=server)

        service = ExecutionLogService(db_session)
        created_log = await service.create_log(
            tool_id=tool.id,
            server_id=server.id,
            tool_name="test_tool",
            input_args={"key": "value"},
            result={"status": "ok"},
            duration_ms=42,
            success=True,
            executed_by="user@test.com",
        )

        fetched_log = await service.get_log(created_log.id)

        assert fetched_log is not None
        assert fetched_log.id == created_log.id
        assert fetched_log.tool_id == tool.id
        assert fetched_log.tool_name == "test_tool"
        assert fetched_log.duration_ms == 42
        assert fetched_log.success is True

    async def test_get_nonexistent_log(self, db_session, server_factory):
        """Getting a nonexistent log returns None."""
        # Need server_factory so db_session has tables created
        await server_factory()

        service = ExecutionLogService(db_session)
        result = await service.get_log(uuid4())

        assert result is None


class TestCleanup:
    """Tests for ExecutionLogService.cleanup()."""

    async def test_cleanup(self, db_session, server_factory, tool_factory):
        """Create > max_per_tool logs, run cleanup, verify old ones removed."""
        server = await server_factory()
        tool = await tool_factory(server=server)

        service = ExecutionLogService(db_session)

        max_per_tool = 3
        total_logs = 7

        # Create more logs than max_per_tool
        created_logs = []
        for i in range(total_logs):
            log = await service.create_log(
                tool_id=tool.id,
                server_id=server.id,
                tool_name="test_tool",
                input_args={"seq": i},
                success=True,
            )
            created_logs.append(log)
            await db_session.flush()

        # Verify all logs exist
        logs_before, total_before = await service.list_by_tool(tool.id)
        assert total_before == total_logs

        # Run cleanup
        deleted_count = await service.cleanup(max_per_tool=max_per_tool)

        # Should have deleted at least (total_logs - max_per_tool) logs
        assert deleted_count >= total_logs - max_per_tool

        # Verify remaining logs are within the limit
        logs_after, total_after = await service.list_by_tool(tool.id)
        assert total_after <= max_per_tool

    async def test_cleanup_no_excess(self, db_session, server_factory, tool_factory):
        """Cleanup with fewer logs than max_per_tool deletes nothing."""
        server = await server_factory()
        tool = await tool_factory(server=server)

        service = ExecutionLogService(db_session)

        # Create only 2 logs with max_per_tool=5
        for i in range(2):
            await service.create_log(
                tool_id=tool.id,
                server_id=server.id,
                tool_name="test_tool",
                input_args={"seq": i},
                success=True,
            )

        deleted_count = await service.cleanup(max_per_tool=5)

        assert deleted_count == 0

        logs, total = await service.list_by_tool(tool.id)
        assert total == 2


class TestRedactArgs:
    """Tests for ExecutionLogService._redact_args()."""

    def test_redact_sensitive_keys(self, db_session):
        """Multiple sensitive keys should all be redacted."""
        service = ExecutionLogService(db_session)

        args = {
            "password": "secret123",
            "api_key": "abc-123",
            "token": "tok_xyz",
            "authorization": "Bearer xxx",
            "credential": "cred_value",
            "query": "safe_value",
        }
        result = service._redact_args(args)

        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"
        assert result["authorization"] == "[REDACTED]"
        assert result["credential"] == "[REDACTED]"
        assert result["query"] == "safe_value"

    def test_redact_none_args(self, db_session):
        """None input should return None."""
        service = ExecutionLogService(db_session)
        assert service._redact_args(None) is None

    def test_redact_empty_args(self, db_session):
        """Empty dict should return empty dict (falsy, so returns as-is)."""
        service = ExecutionLogService(db_session)
        assert service._redact_args({}) == {}

    def test_redact_nested_dict(self, db_session):
        """Sensitive keys inside nested dicts should be redacted."""
        service = ExecutionLogService(db_session)

        args = {
            "config": {
                "password": "nested_secret",
                "host": "localhost",
            },
        }
        result = service._redact_args(args)

        assert result["config"]["password"] == "[REDACTED]"
        assert result["config"]["host"] == "localhost"


class TestTruncateResult:
    """Tests for ExecutionLogService._truncate_result()."""

    def test_truncate_none(self, db_session):
        """None result should return None."""
        service = ExecutionLogService(db_session)
        assert service._truncate_result(None) is None

    def test_truncate_small_result(self, db_session):
        """Small result should be returned unchanged."""
        service = ExecutionLogService(db_session)
        result = {"status": "ok", "count": 42}
        assert service._truncate_result(result) == result

    def test_truncate_large_result(self, db_session):
        """Result > 10,000 chars should be truncated."""
        service = ExecutionLogService(db_session)
        large_result = {"data": "x" * 15_000}
        truncated = service._truncate_result(large_result)

        assert truncated["_truncated"] is True
        assert "_preview" in truncated
        assert len(truncated["_preview"]) <= 1100  # 1000 + "..."
