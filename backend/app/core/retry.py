"""Retry utilities with exponential backoff."""

import asyncio
import functools
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)


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
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry logic.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        config: Retry configuration
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
            result = await func(*args, **kwargs)
            return result

        except Exception as e:
            last_exception = e

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
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for adding retry logic to async functions.

    Args:
        config: Retry configuration

    Example:
        @with_retry(config=RetryConfig(max_retries=3))
        async def fetch_data():
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_async(
                func,
                *args,
                config=config,
                **kwargs,
            )

        return wrapper

    return decorator


class RetryableHTTPClient:
    """HTTP client wrapper with built-in retry support."""

    def __init__(
        self,
        service_name: str,
        base_url: str = "",
        timeout: float = 30.0,
        retry_config: RetryConfig | None = None,
    ):
        self.service_name = service_name
        self.base_url = base_url
        self.timeout = timeout
        self.retry_config = retry_config or RetryConfig()
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
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request with retry."""

        async def do_request() -> httpx.Response:
            client = await self._get_client()
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response

        result = await retry_async(
            do_request,
            config=self.retry_config,
        )
        return cast(httpx.Response, result)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a GET request."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a POST request."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a PUT request."""
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a DELETE request."""
        return await self.request("DELETE", url, **kwargs)
