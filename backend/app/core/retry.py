"""Retry utilities with exponential backoff and circuit breaker pattern."""

import asyncio
import functools
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests allowed
    OPEN = "open"  # Failure threshold exceeded, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 1.0  # Base delay in seconds
    max_delay: float = 30.0  # Maximum delay in seconds
    exponential_base: float = 2.0  # Exponential backoff multiplier
    jitter: bool = True  # Add random jitter to delays
    retryable_exceptions: tuple = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.NetworkError,
        ConnectionError,
        TimeoutError,
    )
    retryable_status_codes: tuple = (502, 503, 504, 429)  # Gateway errors, rate limits


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 5  # Failures before opening circuit
    success_threshold: int = 2  # Successes in half-open before closing
    timeout: float = 60.0  # Seconds before attempting half-open
    excluded_exceptions: tuple = ()  # Exceptions that don't count as failures


@dataclass
class CircuitBreakerState:
    """Mutable state for circuit breaker."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""

    def __init__(self, service_name: str, retry_after: float):
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker open for {service_name}. Retry after {retry_after:.1f}s")


class CircuitBreaker:
    """Circuit breaker implementation for external services."""

    # Class-level registry of circuit breakers by service name
    _instances: dict[str, "CircuitBreaker"] = {}

    def __init__(
        self,
        service_name: str,
        config: CircuitBreakerConfig | None = None,
    ):
        self.service_name = service_name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitBreakerState()
        self._lock = asyncio.Lock()

    @classmethod
    def get_or_create(
        cls,
        service_name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> "CircuitBreaker":
        """Get existing circuit breaker or create new one."""
        if service_name not in cls._instances:
            cls._instances[service_name] = cls(service_name, config)
        return cls._instances[service_name]

    @classmethod
    def get_all_states(cls) -> dict[str, dict]:
        """Get states of all circuit breakers."""
        return {name: cb.get_state() for name, cb in list(cls._instances.items())}

    @classmethod
    async def reset_all(cls) -> None:
        """Reset all circuit breakers."""
        for cb in list(cls._instances.values()):
            await cb.reset()

    def get_state(self) -> dict:
        """Get current circuit breaker state."""
        return {
            "service_name": self.service_name,
            "state": self._state.state.value,
            "failure_count": self._state.failure_count,
            "success_count": self._state.success_count,
            "last_failure_time": self._state.last_failure_time,
        }

    async def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        async with self._lock:
            self._state = CircuitBreakerState()
        logger.info(f"Circuit breaker reset for {self.service_name}")

    async def _check_state(self) -> None:
        """Check and potentially transition circuit state."""
        async with self._lock:
            if self._state.state == CircuitState.OPEN:
                # Check if timeout has elapsed
                if self._state.last_failure_time:
                    elapsed = time.monotonic() - self._state.last_failure_time
                    if elapsed >= self.config.timeout:
                        logger.info(f"Circuit breaker half-opening for {self.service_name}")
                        self._state.state = CircuitState.HALF_OPEN
                        self._state.success_count = 0
                    else:
                        raise CircuitBreakerOpen(
                            self.service_name,
                            self.config.timeout - elapsed,
                        )

    async def record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self._state.state == CircuitState.HALF_OPEN:
                self._state.success_count += 1
                if self._state.success_count >= self.config.success_threshold:
                    logger.info(f"Circuit breaker closing for {self.service_name}")
                    self._state.state = CircuitState.CLOSED
                    self._state.failure_count = 0
            elif self._state.state == CircuitState.CLOSED:
                # Reset failure count on success
                self._state.failure_count = 0

    async def record_failure(self, exception: Exception) -> None:
        """Record a failed call."""
        # Don't count excluded exceptions
        if isinstance(exception, self.config.excluded_exceptions):
            return

        async with self._lock:
            self._state.failure_count += 1
            self._state.last_failure_time = time.monotonic()

            if self._state.state == CircuitState.HALF_OPEN:
                # Any failure in half-open reopens the circuit
                logger.warning(f"Circuit breaker reopening for {self.service_name}: {exception}")
                self._state.state = CircuitState.OPEN
            elif self._state.state == CircuitState.CLOSED:
                if self._state.failure_count >= self.config.failure_threshold:
                    logger.warning(
                        f"Circuit breaker opening for {self.service_name}: "
                        f"{self._state.failure_count} failures"
                    )
                    self._state.state = CircuitState.OPEN

    async def __aenter__(self) -> "CircuitBreaker":
        """Context manager entry - check if requests allowed."""
        await self._check_state()
        return self

    async def __aexit__(self, exc_type, exc_val, _exc_tb) -> bool:
        """Context manager exit - record success/failure."""
        if exc_type is None:
            await self.record_success()
        elif exc_val is not None:
            await self.record_failure(exc_val)
        return False  # Don't suppress exceptions


def calculate_backoff_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    """Calculate delay for exponential backoff with optional jitter."""
    delay = config.base_delay * (config.exponential_base**attempt)
    delay = min(delay, config.max_delay)

    if config.jitter:
        # Add random jitter (0.5 to 1.5 times the delay)
        delay = delay * (0.5 + random.random())

    return delay


async def retry_async(
    func: Callable[..., Any],
    *args,
    config: RetryConfig | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    **kwargs,
) -> Any:
    """Execute an async function with retry logic.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        config: Retry configuration
        circuit_breaker: Optional circuit breaker to use
        **kwargs: Keyword arguments for func

    Returns:
        Result of func

    Raises:
        The last exception if all retries fail
    """
    config = config or RetryConfig()
    last_exception: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            # Check circuit breaker if provided
            if circuit_breaker:
                await circuit_breaker._check_state()

            result = await func(*args, **kwargs)

            # Record success
            if circuit_breaker:
                await circuit_breaker.record_success()

            return result

        except CircuitBreakerOpen:
            # Don't retry if circuit is open
            raise

        except Exception as e:
            last_exception = e

            # Record failure in circuit breaker
            if circuit_breaker:
                await circuit_breaker.record_failure(e)

            # Check if exception is retryable
            is_retryable = isinstance(e, config.retryable_exceptions)

            # Check if it's an HTTP error with retryable status
            if isinstance(e, httpx.HTTPStatusError):
                is_retryable = e.response.status_code in config.retryable_status_codes

            if not is_retryable or attempt >= config.max_retries:
                logger.warning(f"Retry failed after {attempt + 1} attempts: {e}")
                raise

            delay = calculate_backoff_delay(attempt, config)
            logger.info(
                f"Retry attempt {attempt + 1}/{config.max_retries} after {delay:.2f}s delay: {e}"
            )
            await asyncio.sleep(delay)

    # Should not reach here, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry logic error")


def with_retry(
    config: RetryConfig | None = None,
    circuit_breaker_name: str | None = None,
    circuit_breaker_config: CircuitBreakerConfig | None = None,
):
    """Decorator for adding retry logic to async functions.

    Args:
        config: Retry configuration
        circuit_breaker_name: Name for circuit breaker (creates if not exists)
        circuit_breaker_config: Configuration for circuit breaker

    Example:
        @with_retry(config=RetryConfig(max_retries=3))
        async def fetch_data():
            ...

        @with_retry(circuit_breaker_name="external_api")
        async def call_external_api():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            cb = None
            if circuit_breaker_name:
                cb = CircuitBreaker.get_or_create(
                    circuit_breaker_name,
                    circuit_breaker_config,
                )

            return await retry_async(
                func,
                *args,
                config=config,
                circuit_breaker=cb,
                **kwargs,
            )

        return wrapper

    return decorator


class RetryableHTTPClient:
    """HTTP client wrapper with built-in retry and circuit breaker support."""

    def __init__(
        self,
        service_name: str,
        base_url: str = "",
        timeout: float = 30.0,
        retry_config: RetryConfig | None = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
    ):
        self.service_name = service_name
        self.base_url = base_url
        self.timeout = timeout
        self.retry_config = retry_config or RetryConfig()
        self.circuit_breaker = CircuitBreaker.get_or_create(
            service_name,
            circuit_breaker_config,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with retry and circuit breaker."""

        async def do_request():
            client = await self._get_client()
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response

        return await retry_async(
            do_request,
            config=self.retry_config,
            circuit_breaker=self.circuit_breaker,
        )

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Make a GET request."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Make a POST request."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Make a PUT request."""
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """Make a DELETE request."""
        return await self.request("DELETE", url, **kwargs)
