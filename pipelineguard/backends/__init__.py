"""Backend implementations for PipelineGuard (GitLab) and SplunkGuard (Splunk)."""
from .direct import DirectBackend
from .mcp import MCPBackend
from .splunk_direct import SplunkDirectBackend
from .splunk_mcp import SplunkMCPBackend

__all__ = ["MCPBackend", "DirectBackend", "SplunkMCPBackend", "SplunkDirectBackend"]
