"""Tests for sandbox concurrency limiting and memory cleanup.

The sandbox limits concurrent tool executions via an asyncio.Semaphore
to prevent memory exhaustion when multiple heavy tools run simultaneously.
After every execution (success, error, or timeout) gc.collect() is called
to reclaim memory left by cancelled coroutines and closed HTTP clients.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.registry import (
    EXECUTION_QUEUE_TIMEOUT,
    MAX_CONCURRENT_EXECUTIONS,
    ToolRegistry,
)


class TestConcurrencyConfig:
    """Verify config values are read correctly."""

    def test_default_max_concurrent(self):
        """Default max concurrent executions is 3."""
        assert MAX_CONCURRENT_EXECUTIONS == 3

    def test_default_queue_timeout(self):
        """Default queue timeout is 120 seconds."""
        assert EXECUTION_QUEUE_TIMEOUT == 120.0

    def test_config_from_env(self):
        """Config reads from environment variables."""
        with patch.dict(
            "os.environ",
            {"SANDBOX_MAX_CONCURRENT_EXECUTIONS": "5"},
        ):
            # Re-import to pick up new env var
            import importlib

            import app.registry as reg_module

            importlib.reload(reg_module)
            assert reg_module.MAX_CONCURRENT_EXECUTIONS == 5

            # Restore default
            with patch.dict(
                "os.environ",
                {"SANDBOX_MAX_CONCURRENT_EXECUTIONS": "3"},
            ):
                importlib.reload(reg_module)


class TestConcurrencySemaphore:
    """Test that the semaphore correctly limits concurrent executions."""

    @pytest.fixture
    def registry_with_tool(self):
        """Create a registry with a slow Python tool registered."""
        registry = ToolRegistry()
        registry.register_server(
            server_id="test-server",
            server_name="test",
            tools=[
                {
                    "name": "slow_tool",
                    "description": "A tool that sleeps",
                    "parameters": {"type": "object", "properties": {}},
                    "python_code": (
                        "import asyncio\n"
                        "async def main():\n"
                        "    await asyncio.sleep(0.5)\n"
                        "    return 'done'\n"
                    ),
                }
            ],
        )
        return registry

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_executions(self):
        """Only MAX_CONCURRENT_EXECUTIONS tools run at once; others queue."""
        execution_order = []
        concurrency_high_water = [0]
        active_count = [0]

        async def mock_execute_python(self, tool, arguments, debug_mode=False):
            idx = len(execution_order)
            execution_order.append(f"start-{idx}")
            active_count[0] += 1
            concurrency_high_water[0] = max(concurrency_high_water[0], active_count[0])
            await asyncio.sleep(0.1)
            active_count[0] -= 1
            execution_order.append(f"end-{idx}")
            return {"success": True, "result": f"result-{idx}"}

        registry = ToolRegistry()
        registry.register_server(
            server_id="s1",
            server_name="test",
            tools=[
                {
                    "name": "tool",
                    "description": "test",
                    "parameters": {"type": "object", "properties": {}},
                    "python_code": "async def main(): pass",
                }
            ],
        )

        # Reset module-level semaphore to use a fresh one with limit=2
        import app.registry as reg_module

        old_sem = reg_module._execution_semaphore
        reg_module._execution_semaphore = asyncio.Semaphore(2)

        try:
            with patch.object(
                ToolRegistry,
                "_execute_python_tool",
                mock_execute_python,
            ):
                # Launch 4 concurrent executions with limit=2
                results = await asyncio.gather(
                    registry.execute_tool("test__tool", {}),
                    registry.execute_tool("test__tool", {}),
                    registry.execute_tool("test__tool", {}),
                    registry.execute_tool("test__tool", {}),
                )

            # All should succeed
            assert all(r["success"] for r in results)
            # But only 2 should have run at the same time
            assert concurrency_high_water[0] <= 2
        finally:
            reg_module._execution_semaphore = old_sem

    @pytest.mark.asyncio
    async def test_semaphore_timeout_returns_error(self):
        """When queue is full and times out, return a clear error."""
        import app.registry as reg_module

        old_sem = reg_module._execution_semaphore
        old_timeout = reg_module.EXECUTION_QUEUE_TIMEOUT
        # Set semaphore to 1 and timeout to very short
        reg_module._execution_semaphore = asyncio.Semaphore(1)
        reg_module.EXECUTION_QUEUE_TIMEOUT = 0.05  # 50ms

        registry = ToolRegistry()
        registry.register_server(
            server_id="s1",
            server_name="test",
            tools=[
                {
                    "name": "slow",
                    "description": "test",
                    "parameters": {"type": "object", "properties": {}},
                    "python_code": "async def main(): pass",
                }
            ],
        )

        async def slow_execute(self, tool, arguments, debug_mode=False):
            await asyncio.sleep(1.0)
            return {"success": True, "result": "done"}

        try:
            with patch.object(
                ToolRegistry,
                "_execute_python_tool",
                slow_execute,
            ):
                results = await asyncio.gather(
                    registry.execute_tool("test__slow", {}),
                    registry.execute_tool("test__slow", {}),
                )

            # One should succeed, one should fail with timeout
            successes = [r for r in results if r["success"]]
            failures = [r for r in results if not r["success"]]
            assert len(successes) == 1
            assert len(failures) == 1
            assert "Sandbox busy" in failures[0]["error"]
            assert failures[0]["error_category"] == "sandbox_error"
        finally:
            reg_module._execution_semaphore = old_sem
            reg_module.EXECUTION_QUEUE_TIMEOUT = old_timeout

    @pytest.mark.asyncio
    async def test_passthrough_tools_skip_semaphore(self):
        """MCP passthrough tools don't consume semaphore slots."""
        import app.registry as reg_module

        old_sem = reg_module._execution_semaphore
        # Set semaphore to 0 — no Python tools can execute
        reg_module._execution_semaphore = asyncio.Semaphore(0)
        reg_module.EXECUTION_QUEUE_TIMEOUT = 0.05

        registry = ToolRegistry()
        registry.register_server(
            server_id="s1",
            server_name="test",
            tools=[
                {
                    "name": "proxy_tool",
                    "description": "proxied tool",
                    "parameters": {"type": "object", "properties": {}},
                    "tool_type": "mcp_passthrough",
                    "external_source_id": "source-1",
                    "external_tool_name": "remote_tool",
                }
            ],
            external_sources=[
                {
                    "source_id": "source-1",
                    "url": "http://example.com/mcp",
                }
            ],
        )

        with patch.object(
            ToolRegistry,
            "_execute_passthrough_tool",
            new_callable=lambda: AsyncMock(
                return_value={"success": True, "result": "proxied"}
            ),
        ):
            # Should not block even though semaphore is 0
            result = await asyncio.wait_for(
                registry.execute_tool("test__proxy_tool", {}),
                timeout=1.0,
            )
            assert result["success"]

        reg_module._execution_semaphore = old_sem

    @pytest.mark.asyncio
    async def test_semaphore_released_on_error(self):
        """Semaphore is released even when tool execution raises."""
        import app.registry as reg_module

        old_sem = reg_module._execution_semaphore
        sem = asyncio.Semaphore(1)
        reg_module._execution_semaphore = sem

        registry = ToolRegistry()
        registry.register_server(
            server_id="s1",
            server_name="test",
            tools=[
                {
                    "name": "crasher",
                    "description": "test",
                    "parameters": {"type": "object", "properties": {}},
                    "python_code": "async def main(): pass",
                }
            ],
        )

        async def exploding_execute(self, tool, arguments, debug_mode=False):
            raise RuntimeError("boom")

        try:
            with patch.object(
                ToolRegistry,
                "_execute_python_tool",
                exploding_execute,
            ):
                with pytest.raises(RuntimeError, match="boom"):
                    await registry.execute_tool("test__crasher", {})

            # Semaphore should be released — value back to 1
            # (we can acquire without blocking)
            acquired = await asyncio.wait_for(sem.acquire(), timeout=0.1)
            assert acquired
            sem.release()
        finally:
            reg_module._execution_semaphore = old_sem

    @pytest.mark.asyncio
    async def test_tool_not_found_skips_semaphore(self):
        """Tool-not-found returns immediately without touching the semaphore."""
        import app.registry as reg_module

        old_sem = reg_module._execution_semaphore
        # Semaphore at 0 — any acquire would block
        reg_module._execution_semaphore = asyncio.Semaphore(0)
        reg_module.EXECUTION_QUEUE_TIMEOUT = 0.05

        registry = ToolRegistry()

        try:
            result = await asyncio.wait_for(
                registry.execute_tool("nonexistent__tool", {}),
                timeout=1.0,
            )
            assert not result["success"]
            assert "not found" in result["error"]
        finally:
            reg_module._execution_semaphore = old_sem


class TestMemoryCleanup:
    """Verify gc.collect() is called after tool execution to reclaim memory."""

    def _make_registry(self):
        """Create a registry with a simple tool registered."""
        registry = ToolRegistry()
        registry.register_server(
            server_id="s1",
            server_name="test",
            tools=[
                {
                    "name": "tool",
                    "description": "test",
                    "parameters": {"type": "object", "properties": {}},
                    "python_code": "async def main(): return 'ok'",
                }
            ],
        )
        return registry

    @pytest.mark.asyncio
    async def test_gc_collect_after_successful_execution(self):
        """gc.collect() runs after a successful tool execution."""

        async def mock_execute(self, tool, arguments, debug_mode=False):
            return {"success": True, "result": "done"}

        registry = self._make_registry()

        with (
            patch.object(ToolRegistry, "_execute_python_tool", mock_execute),
            patch("app.registry.gc.collect") as mock_gc,
        ):
            result = await registry.execute_tool("test__tool", {})

        assert result["success"]
        mock_gc.assert_called_once()

    @pytest.mark.asyncio
    async def test_gc_collect_after_failed_execution(self):
        """gc.collect() runs even when tool execution raises."""

        async def exploding_execute(self, tool, arguments, debug_mode=False):
            raise RuntimeError("boom")

        registry = self._make_registry()

        with (
            patch.object(ToolRegistry, "_execute_python_tool", exploding_execute),
            patch("app.registry.gc.collect") as mock_gc,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await registry.execute_tool("test__tool", {})

        mock_gc.assert_called_once()

    @pytest.mark.asyncio
    async def test_gc_collect_after_executor_timeout(self):
        """gc.collect() runs in the executor after asyncio.TimeoutError."""
        from app.executor import python_executor

        # asyncio must be in allowed_modules for the tool code to import it
        allowed = {"asyncio"}

        with patch("app.executor.gc.collect") as mock_gc:
            result = await python_executor.execute(
                python_code=(
                    "import asyncio\nasync def main():\n    await asyncio.sleep(10)\n"
                ),
                arguments={},
                http_client=None,
                timeout=0.05,
                allowed_modules=allowed,
            )

        assert not result.success
        assert "timed out" in result.error
        mock_gc.assert_called_once()
