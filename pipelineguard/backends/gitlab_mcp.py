"""Backend for the official GitLab MCP server (https://gitlab.com/api/v4/mcp).

This is the partner MCP server required by the Google Cloud Rapid Agent
Hackathon (GitLab track).  It runs alongside PipelineGuard's own bundled
pipeline MCP server so Gemini has both general GitLab context tools (projects,
MRs, issues, branches) and deep pipeline-specific tooling (job logs, failure
categories, fix proposals).

Authentication: GitLab PAT via ``Authorization: Bearer`` header.
Tool names are prefixed with ``gl_`` using GitLab's server-side
``X-Gitlab-Mcp-Server-Tool-Name-Prefix`` header to prevent name collisions
with PipelineGuard's pipeline tools.

If the server is unreachable or authentication fails the backend degrades
gracefully to an empty tool set — the custom pipeline MCP still handles
full diagnosis without interruption.
"""
from __future__ import annotations

import logging
from typing import Any

from google.genai import types
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .mcp import _mcp_to_gemini_declaration

logger = logging.getLogger(__name__)

TOOL_PREFIX = "gl_"
_PREFIX_HEADER = "X-Gitlab-Mcp-Server-Tool-Name-Prefix"


class GitLabOfficialMCPBackend:
    """Wraps the official GitLab MCP server and exposes its tools to Gemini.

    Used alongside ``MCPBackend`` (PipelineGuard's bundled pipeline server).
    The agent merges tools from both; tool calls are routed by the ``gl_``
    prefix — anything prefixed goes here, everything else to the pipeline MCP.
    """

    def __init__(
        self,
        gitlab_token: str,
        gitlab_url: str = "https://gitlab.com",
    ) -> None:
        self._mcp_url = f"{gitlab_url.rstrip('/')}/api/v4/mcp"
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {gitlab_token}",
            _PREFIX_HEADER: TOOL_PREFIX,
        }
        self._session: ClientSession | None = None
        self._cm = None
        self.connected = False

    async def __aenter__(self) -> "GitLabOfficialMCPBackend":
        try:
            self._cm = streamablehttp_client(self._mcp_url, headers=self._headers)
            read, write, _ = await self._cm.__aenter__()
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
            self.connected = True
            logger.info("Official GitLab MCP server connected (%s)", self._mcp_url)
        except Exception as exc:
            logger.warning(
                "Official GitLab MCP server unavailable — %s. "
                "Pipeline diagnosis continues with the bundled MCP server.",
                exc,
            )
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._session:
            try:
                await self._session.__aexit__(*exc_info)
            except Exception:
                pass
        if self._cm:
            try:
                await self._cm.__aexit__(*exc_info)
            except Exception:
                pass

    async def list_tools_as_gemini(self) -> list[types.Tool]:
        """Return official GitLab tools as Gemini FunctionDeclarations."""
        if not self.connected or self._session is None:
            return []
        try:
            result = await self._session.list_tools()
            if not result.tools:
                return []
            declarations = [_mcp_to_gemini_declaration(t) for t in result.tools]
            logger.info("Official GitLab MCP: %d tools available", len(declarations))
            return [types.Tool(function_declarations=declarations)]
        except Exception as exc:
            logger.warning("Failed to list tools from official GitLab MCP: %s", exc)
            return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute an official GitLab MCP tool.

        The GitLab server may expect either the prefixed name (``gl_foo``) or
        the original name (``foo``) in call_tool requests — behaviour depends on
        the server version.  We try the prefixed name first; if the call fails
        we retry once with the prefix stripped so the agent always gets a result.
        """
        if not self.connected or self._session is None:
            return "(official GitLab MCP server not connected)"

        async def _call(tool_name: str) -> str:
            result = await self._session.call_tool(tool_name, arguments)  # type: ignore[union-attr]
            parts: list[str] = [
                item.text if hasattr(item, "text") else str(item)
                for item in result.content
            ]
            return "\n".join(parts)

        try:
            return await _call(name)
        except Exception as first_exc:
            # Retry with prefix stripped in case the server expects the bare name.
            if name.startswith(TOOL_PREFIX):
                bare_name = name[len(TOOL_PREFIX):]
                try:
                    return await _call(bare_name)
                except Exception:
                    pass  # fall through to original error
            logger.warning("Tool call %r failed on official GitLab MCP: %s", name, first_exc)
            return f"(error calling {name}: {first_exc})"

    def owns_tool(self, name: str) -> bool:
        """True if this backend owns the given tool (``gl_`` prefix match)."""
        return name.startswith(TOOL_PREFIX)
