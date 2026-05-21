"""GitLab backend implementations for PipelineGuard."""
from .direct import DirectBackend
from .mcp import MCPBackend

__all__ = ["MCPBackend", "DirectBackend"]
