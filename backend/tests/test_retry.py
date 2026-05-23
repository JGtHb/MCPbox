"""Tests for retry utilities with exponential backoff."""

from unittest.mock import AsyncMock

import pytest

from app.core.retry import (
    RetryConfig,
    calculate_backoff_delay,
    retry_async,
)

pytestmark = pytest.mark.asyncio


class TestCalculateBackoffDelay:
    """Tests for backoff delay calculation."""

    def test_exponential_growth(self):
        """Delay should grow exponentially."""
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=False)

        delay0 = calculate_backoff_delay(0, config)
        delay1 = calculate_backoff_delay(1, config)
        delay2 = calculate_backoff_delay(2, config)

        assert delay0 == 1.0
        assert delay1 == 2.0
        assert delay2 == 4.0

    def test_max_delay_cap(self):
        """Delay should not exceed max_delay."""
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, max_delay=5.0, jitter=False)

        delay10 = calculate_backoff_delay(10, config)
        assert delay10 == 5.0

    def test_jitter_adds_variance(self):
        """Jitter should produce different delays for the same attempt."""
        config = RetryConfig(base_delay=1.0, jitter=True)

        delays = {calculate_backoff_delay(0, config) for _ in range(20)}
        # With jitter, we should get some variance
        assert len(delays) > 1


class TestRetryAsyncBasic:
    """Tests for basic retry_async behavior."""

    async def test_returns_on_success(self):
        """Should return result on first success."""
        func = AsyncMock(return_value=42)
        result = await retry_async(func)
        assert result == 42
        assert func.call_count == 1

    async def test_retries_on_retryable_error(self):
        """Should retry on retryable errors."""
        func = AsyncMock(side_effect=[ConnectionError("fail"), ConnectionError("fail"), "ok"])
        config = RetryConfig(max_retries=3, base_delay=0.001)
        result = await retry_async(func, config=config)
        assert result == "ok"
        assert func.call_count == 3

    async def test_no_retry_on_non_retryable_error(self):
        """Should not retry on non-retryable errors."""
        func = AsyncMock(side_effect=ValueError("bad"))
        config = RetryConfig(max_retries=3, base_delay=0.001)
        with pytest.raises(ValueError):
            await retry_async(func, config=config)
        assert func.call_count == 1

    async def test_exhausts_retries_then_raises(self):
        """Should raise after all retries are exhausted."""
        func = AsyncMock(side_effect=ConnectionError("refused"))
        config = RetryConfig(max_retries=3, base_delay=0.001)

        with pytest.raises(ConnectionError):
            await retry_async(func, config=config)

        assert func.call_count == 4  # 1 initial + 3 retries
