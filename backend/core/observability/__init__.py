"""Optional Langfuse tracing helpers (no-op when credentials are absent)."""

from backend.core.observability.agent_observe import agent_observe, is_langfuse_configured

__all__ = ["agent_observe", "is_langfuse_configured"]
