"""Tests for retry utilities and circuit breaker core logic.

Covers the circuit breaker state machine, retry amplification prevention,
timer reset behavior, and recovery flow.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.retry import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
    RetryConfig,
    calculate_backoff_delay,
    retry_async,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def isolate_circuit_breakers():
    """Ensure each test gets a fresh circuit breaker registry."""
    saved = dict(CircuitBreaker._instances)
    CircuitBreaker._instances.clear()
    yield
    CircuitBreaker._instances.clear()
    CircuitBreaker._instances.update(saved)


class TestCircuitBreakerTimerReset:
    """Tests for the timer reset bug fix.

    Bug: record_failure() used to update last_failure_time even when the
    circuit was already OPEN, preventing the recovery timeout from ever
    elapsing. Fixed by returning early when state is OPEN.
    """

    async def test_record_failure_does_not_reset_timer_when_open(self):
        """Failures while OPEN should not reset the recovery timer."""
        config = CircuitBreakerConfig(failure_threshold=2, timeout=10.0)
        cb = CircuitBreaker("timer_test", config)

        # Trip the circuit
        await cb.record_failure(Exception("fail 1"))
        await cb.record_failure(Exception("fail 2"))
        assert cb._state.state == CircuitState.OPEN

        # Record the time when circuit opened
        open_time = cb._state.last_failure_time

        # Simulate time passing then recording another failure
        await asyncio.sleep(0.01)
        await cb.record_failure(Exception("fail while open"))

        # Timer should NOT have been reset
        assert cb._state.last_failure_time == open_time

    async def test_failure_count_does_not_increase_when_open(self):
        """Failure count should not increase when circuit is already OPEN."""
        config = CircuitBreakerConfig(failure_threshold=2, timeout=10.0)
        cb = CircuitBreaker("count_test", config)

        await cb.record_failure(Exception("fail 1"))
        await cb.record_failure(Exception("fail 2"))
        assert cb._state.state == CircuitState.OPEN
        assert cb._state.failure_count == 2

        # Additional failures should be ignored
        await cb.record_failure(Exception("fail 3"))
        await cb.record_failure(Exception("fail 4"))
        assert cb._state.failure_count == 2

    async def test_circuit_recovers_after_timeout(self):
        """Circuit should transition to HALF_OPEN after timeout elapses."""
        config = CircuitBreakerConfig(failure_threshold=2, timeout=0.05)
        cb = CircuitBreaker("recovery_test", config)

        # Trip the circuit
        await cb.record_failure(Exception("fail 1"))
        await cb.record_failure(Exception("fail 2"))
        assert cb._state.state == CircuitState.OPEN

        # Wait for timeout
        await asyncio.sleep(0.1)

        # _check_state should transition to HALF_OPEN
        await cb._check_state()
        assert cb._state.state == CircuitState.HALF_OPEN

    async def test_half_open_to_closed_on_success(self):
        """Circuit should close after success_threshold successes in HALF_OPEN."""
        config = CircuitBreakerConfig(failure_threshold=2, timeout=0.05, success_threshold=1)
        cb = CircuitBreaker("close_test", config)

        # Trip the circuit
        await cb.record_failure(Exception("fail 1"))
        await cb.record_failure(Exception("fail 2"))

        # Wait for timeout
        await asyncio.sleep(0.1)
        await cb._check_state()
        assert cb._state.state == CircuitState.HALF_OPEN

        # Record success → should close
        await cb.record_success()
        assert cb._state.state == CircuitState.CLOSED
        assert cb._state.failure_count == 0

    async def test_half_open_failure_reopens_circuit(self):
        """A failure in HALF_OPEN should reopen the circuit with a fresh timer."""
        config = CircuitBreakerConfig(failure_threshold=2, timeout=0.05)
        cb = CircuitBreaker("reopen_test", config)

        # Trip → wait → half-open
        await cb.record_failure(Exception("fail 1"))
        await cb.record_failure(Exception("fail 2"))
        original_time = cb._state.last_failure_time

        await asyncio.sleep(0.1)
        await cb._check_state()
        assert cb._state.state == CircuitState.HALF_OPEN

        # Fail in half-open → reopen with new timer
        await cb.record_failure(Exception("fail in half-open"))
        assert cb._state.state == CircuitState.OPEN
        assert cb._state.last_failure_time > original_time


class TestRetryAmplification:
    """Tests for the retry amplification fix.

    Bug: retry_async() used to call record_failure() on every retry attempt.
    With max_retries=3, one failing request would record 4 failures, making
    it trivial to trip the circuit. Fixed by recording only a single failure
    after all retries are exhausted.
    """

    async def test_single_failure_recorded_after_retries_exhausted(self):
        """Only one failure should be recorded even with multiple retry attempts."""
        config = CircuitBreakerConfig(failure_threshold=5, timeout=30.0)
        cb = CircuitBreaker("amplification_test", config)
        retry_config = RetryConfig(
            max_retries=3,
            base_delay=0.001,
            retryable_exceptions=(ConnectionError,),
        )

        failing_func = AsyncMock(side_effect=ConnectionError("refused"))

        with pytest.raises(ConnectionError):
            await retry_async(
                failing_func,
                config=retry_config,
                circuit_breaker=cb,
            )

        # 4 attempts but only 1 failure recorded
        assert failing_func.call_count == 4
        assert cb._state.failure_count == 1
        assert cb._state.state == CircuitState.CLOSED  # Still below threshold

    async def test_non_retryable_records_single_failure(self):
        """Non-retryable exceptions should record exactly one failure."""
        config = CircuitBreakerConfig(failure_threshold=5, timeout=30.0)
        cb = CircuitBreaker("non_retryable_test", config)
        retry_config = RetryConfig(
            max_retries=3,
            base_delay=0.001,
            retryable_exceptions=(ConnectionError,),  # ValueError is NOT retryable
        )

        failing_func = AsyncMock(side_effect=ValueError("bad input"))

        with pytest.raises(ValueError):
            await retry_async(
                failing_func,
                config=retry_config,
                circuit_breaker=cb,
            )

        # Only 1 attempt (not retryable) and 1 failure recorded
        assert failing_func.call_count == 1
        assert cb._state.failure_count == 1

    async def test_multiple_requests_needed_to_trip_circuit(self):
        """It should take failure_threshold distinct failing requests to trip the circuit."""
        threshold = 5
        config = CircuitBreakerConfig(failure_threshold=threshold, timeout=30.0)
        cb = CircuitBreaker("trip_test", config)
        retry_config = RetryConfig(
            max_retries=3,
            base_delay=0.001,
            retryable_exceptions=(ConnectionError,),
        )

        failing_func = AsyncMock(side_effect=ConnectionError("refused"))

        # Each request should add exactly 1 failure
        for i in range(threshold - 1):
            with pytest.raises(ConnectionError):
                await retry_async(
                    failing_func,
                    config=retry_config,
                    circuit_breaker=cb,
                )
            assert cb._state.failure_count == i + 1
            assert cb._state.state == CircuitState.CLOSED

        # One more should trip it
        with pytest.raises(ConnectionError):
            await retry_async(
                failing_func,
                config=retry_config,
                circuit_breaker=cb,
            )
        assert cb._state.failure_count == threshold
        assert cb._state.state == CircuitState.OPEN

    async def test_success_resets_failure_count(self):
        """A successful request should reset the failure count."""
        config = CircuitBreakerConfig(failure_threshold=5, timeout=30.0)
        cb = CircuitBreaker("success_reset_test", config)
        retry_config = RetryConfig(max_retries=0, base_delay=0.001)

        # Record some failures
        failing_func = AsyncMock(side_effect=ConnectionError("refused"))
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await retry_async(failing_func, config=retry_config, circuit_breaker=cb)
        assert cb._state.failure_count == 3

        # Successful request resets count
        success_func = AsyncMock(return_value="ok")
        result = await retry_async(success_func, config=retry_config, circuit_breaker=cb)
        assert result == "ok"
        assert cb._state.failure_count == 0


class TestCircuitBreakerOpen:
    """Tests for CircuitBreakerOpen exception behavior."""

    async def test_open_circuit_raises_immediately(self):
        """Open circuit should raise CircuitBreakerOpen without calling the function."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=60.0)
        cb = CircuitBreaker("open_test", config)

        # Trip the circuit
        await cb.record_failure(Exception("fail"))
        assert cb._state.state == CircuitState.OPEN

        # Retry should raise CircuitBreakerOpen without calling the function
        func = AsyncMock(return_value="ok")
        with pytest.raises(CircuitBreakerOpen) as exc_info:
            await retry_async(func, circuit_breaker=cb)

        assert func.call_count == 0
        assert exc_info.value.retry_after > 0
        assert "open_test" in str(exc_info.value)

    async def test_retry_after_decreases_over_time(self):
        """retry_after should reflect actual time remaining, not static value."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=1.0)
        cb = CircuitBreaker("countdown_test", config)

        await cb.record_failure(Exception("fail"))

        # Check retry_after immediately
        try:
            await cb._check_state()
        except CircuitBreakerOpen as e:
            first_retry_after = e.retry_after

        # Wait a bit
        await asyncio.sleep(0.2)

        # retry_after should have decreased
        try:
            await cb._check_state()
        except CircuitBreakerOpen as e:
            second_retry_after = e.retry_after

        assert second_retry_after < first_retry_after


class TestCircuitBreakerGetState:
    """Tests for get_state() including config details."""

    def test_get_state_includes_config(self):
        """get_state() should include configuration for observability."""
        config = CircuitBreakerConfig(failure_threshold=10, success_threshold=1, timeout=30.0)
        cb = CircuitBreaker("config_test", config)
        state = cb.get_state()

        assert "config" in state
        assert state["config"]["failure_threshold"] == 10
        assert state["config"]["success_threshold"] == 1
        assert state["config"]["timeout"] == 30.0


class TestExcludedExceptions:
    """Tests for excluded exceptions behavior."""

    async def test_excluded_exception_not_counted(self):
        """Excluded exceptions should not increment failure count."""
        config = CircuitBreakerConfig(failure_threshold=2, excluded_exceptions=(ValueError,))
        cb = CircuitBreaker("excluded_test", config)

        # ValueError is excluded — should not count
        await cb.record_failure(ValueError("ignored"))
        assert cb._state.failure_count == 0

        # Other exceptions still count
        await cb.record_failure(RuntimeError("counted"))
        assert cb._state.failure_count == 1


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


class TestEndToEndRecovery:
    """End-to-end tests for the full circuit breaker recovery cycle."""

    async def test_full_trip_and_recovery_cycle(self):
        """Circuit trips, waits timeout, half-opens, succeeds, closes."""
        config = CircuitBreakerConfig(failure_threshold=3, timeout=0.05, success_threshold=1)
        cb = CircuitBreaker("e2e_test", config)
        retry_config = RetryConfig(max_retries=0, base_delay=0.001)

        # Trip the circuit with 3 failing requests
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await retry_async(
                    AsyncMock(side_effect=ConnectionError("down")),
                    config=retry_config,
                    circuit_breaker=cb,
                )

        assert cb._state.state == CircuitState.OPEN

        # Requests should be blocked
        with pytest.raises(CircuitBreakerOpen):
            await retry_async(
                AsyncMock(return_value="ok"),
                config=retry_config,
                circuit_breaker=cb,
            )

        # Wait for timeout
        await asyncio.sleep(0.1)

        # Next request should be allowed (half-open probe)
        result = await retry_async(
            AsyncMock(return_value="recovered"),
            config=retry_config,
            circuit_breaker=cb,
        )
        assert result == "recovered"
        assert cb._state.state == CircuitState.CLOSED
        assert cb._state.failure_count == 0

    async def test_concurrent_failures_dont_prevent_recovery(self):
        """Multiple concurrent failures while OPEN should not prevent recovery."""
        config = CircuitBreakerConfig(failure_threshold=2, timeout=0.05, success_threshold=1)
        cb = CircuitBreaker("concurrent_test", config)

        # Trip the circuit
        await cb.record_failure(Exception("fail 1"))
        await cb.record_failure(Exception("fail 2"))
        assert cb._state.state == CircuitState.OPEN
        open_time = cb._state.last_failure_time

        # Simulate many concurrent failures arriving while open
        for _ in range(20):
            await cb.record_failure(Exception("concurrent fail"))

        # Timer should not have been reset
        assert cb._state.last_failure_time == open_time

        # Recovery should still work after timeout
        await asyncio.sleep(0.1)
        await cb._check_state()
        assert cb._state.state == CircuitState.HALF_OPEN
