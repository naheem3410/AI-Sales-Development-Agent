"""
Langfuse `@observe`-style decorators for agent entrypoints.

When ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are unset or empty,
returns an identity decorator so agent behavior is unchanged.

Uses ``LANGFUSE_BASE_URL`` (same as Langfuse Python SDK) for region/host.
"""

from __future__ import annotations

import os
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def is_langfuse_configured() -> bool:
    pub = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    sec = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
    return bool(pub and sec)


def agent_observe(name: str, **observe_kwargs: Any) -> Callable[[F], F]:
    """
    Langfuse observe decorator for async/sync functions, or identity when disabled.

    Typical usage::

        @agent_observe(\"reply_agent\", as_type=\"agent\")
        async def run_reply_agent(...):
            ...
    """
    if not is_langfuse_configured():

        def _noop_decorator(fn: F) -> F:
            return fn

        return _noop_decorator

    from langfuse import observe as lf_observe

    return lf_observe(name=name, **observe_kwargs)
