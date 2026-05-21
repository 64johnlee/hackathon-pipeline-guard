"""MCP backend — connects to the official GitLab MCP server via subprocess."""
from __future__ import annotations

import logging
import os
import shutil
from typing import Any

from google.genai import types

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import Tool as MCPTool
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    stdio_client = None  # type: ignore[assignment]
    MCPTool = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


class MCPBackend:
    """
    Manages a `@gitlab-org/mcp-gitlab` subprocess (via npx) and exposes
    its tools as Gemini FunctionDeclaration objects for the agent loop.
    """

    def __init__(self, gitlab_token: str, gitlab_url: str = "https://gitlab.com") -> None:
        self._gitlab_token = gitlab_token
        self._gitlab_url = gitlab_url
        self._session: ClientSession | None = None
        self._stdio_cm = None

    @staticmethod
    def is_available() -> bool:
        """Return True if both npx (Node) and the mcp package are present."""
        return _MCP_AVAILABLE and shutil.which("npx") is not None

    async def __aenter__(self) -> "MCPBackend":
        if not _MCP_AVAILABLE:
            raise RuntimeError(
                "The 'mcp' Python package is not installed. "
                "Run: pip install mcp  — or use --direct to skip the MCP server."
            )
        env = {
            **os.environ,
            "GITLAB_TOKEN": self._gitlab_token,
            "GITLAB_URL": self._gitlab_url,
        }
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@gitlab-org/mcp-gitlab"],
            env=env,
        )
        logger.info("Starting GitLab MCP server via npx (first run may take ~30s to download)…")
        self._stdio_cm = stdio_client(server_params)
        read, write = await self._stdio_cm.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        logger.debug("GitLab MCP server ready")
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._session:
            await self._session.__aexit__(*exc_info)
        if self._stdio_cm:
            await self._stdio_cm.__aexit__(*exc_info)

    async def list_tools_as_gemini(self) -> list[types.Tool]:
        """Return the MCP server's tool list converted to Gemini Tool objects."""
        assert self._session is not None
        result = await self._session.list_tools()
        declarations = [_mcp_to_gemini_declaration(t) for t in result.tools]
        logger.debug("Loaded %d tools from GitLab MCP server", len(declarations))
        return [types.Tool(function_declarations=declarations)]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute an MCP tool and return its text output."""
        assert self._session is not None
        result = await self._session.call_tool(name, arguments)
        if result.isError:
            logger.warning("MCP tool %r returned an error", name)
        parts: list[str] = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
            else:
                parts.append(str(item))
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Schema conversion helpers
# ---------------------------------------------------------------------------

def _mcp_to_gemini_declaration(tool: MCPTool) -> types.FunctionDeclaration:
    schema = tool.inputSchema or {}
    properties: dict[str, types.Schema] = {}
    for prop_name, prop_def in schema.get("properties", {}).items():
        properties[prop_name] = types.Schema(
            type=_json_type_to_gemini(prop_def.get("type", "string")),
            description=prop_def.get("description", ""),
        )
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description or "",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties=properties,
            required=schema.get("required", []),
        ),
    )


def _json_type_to_gemini(json_type: str) -> types.Type:
    return {
        "string": types.Type.STRING,
        "integer": types.Type.INTEGER,
        "number": types.Type.NUMBER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
        "object": types.Type.OBJECT,
    }.get(json_type, types.Type.STRING)
