from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

T = TypeVar("T")


class RetryableError(RuntimeError):
    """Raised when an operation should be retried."""


def with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    initial_seconds: float = 2,
    max_seconds: float = 120,
) -> T:
    """Run a callable with exponential backoff for transient failures."""

    @retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=initial_seconds, max=max_seconds),
        retry=retry_if_exception_type((RetryableError, TimeoutError, ConnectionError)),
    )
    def _wrapped() -> T:
        return fn()

    return _wrapped()
