"""
Shared constants and helpers for batched LLM workloads (chunk size 3, parallel cap 2).
"""

from __future__ import annotations

from typing import Awaitable, Callable, List, Tuple, TypeVar

from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

BATCH_SIZE = 3
MAX_PARALLEL = 2

T = TypeVar("T")


def chunk_indices(n: int, size: int = BATCH_SIZE) -> List[Tuple[int, int]]:
    """Return half-open slices (start, end) covering range(n)."""
    out: List[Tuple[int, int]] = []
    i = 0
    while i < n:
        out.append((i, min(i + size, n)))
        i += size
    return out


async def async_run_with_retries(fn: Callable[[], Awaitable[T]]) -> T:
    """Run an async callable with 3 total attempts and exponential backoff (2–120s)."""
    retrying = AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=120),
        reraise=True,
    )

    async def _call() -> T:
        return await fn()

    return await retrying(_call)
