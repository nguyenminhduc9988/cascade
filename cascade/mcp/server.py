"""MCP server factory (per-workspace).

Creates a lightweight, project-scoped MCP server that exposes the Cascade
agent tools and the operating-contract instructions. If the ``mcp`` SDK is
installed, a real MCP server is built; otherwise a portable registry object is
returned that can be invoked directly (e.g. from the REST API or tests).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cascade.mcp.instructions import AGENT_INSTRUCTIONS
from cascade.mcp.tools import MCP_TOOLS

logger = logging.getLogger(__name__)


class MCPServerRegistry:
    """Portable registry of project-scoped agent tools.

    ``call`` dispatches to the right tool, injecting the provided session.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.instructions = AGENT_INSTRUCTIONS
        self.tools = MCP_TOOLS

    async def call(
        self, name: str, session: AsyncSession, **arguments: Any
    ) -> Any:
        """Invoke a registered MCP tool by name."""
        fn = self.tools.get(name)
        if fn is None:
            raise KeyError(f"Unknown MCP tool: {name}")
        # Force-scope project_id to this server's workspace when the tool
        # accepts it — this is what makes the server *per-workspace*. A
        # caller-supplied project_id must never override it, or an agent
        # connected to one project's server could read/write another's.
        if "project_id" in fn.__code__.co_varnames[: fn.__code__.co_argcount]:
            arguments["project_id"] = self.project_id
        return await fn(session, **arguments)

    def list_tools(self) -> list[str]:
        """Return the names of all registered tools."""
        return list(self.tools)


def create_mcp_server(project_id: str) -> MCPServerRegistry:
    """Factory: build a per-workspace MCP server registry.

    Attempts to construct a real MCP SDK server when available; always returns
    a :class:`MCPServerRegistry` for direct invocation.
    """
    registry = MCPServerRegistry(project_id)

    try:  # pragma: no cover - optional SDK integration
        from mcp.server import Server  # type: ignore

        server = Server(f"cascade-{project_id}")
        registry._sdk_server = server  # type: ignore[attr-defined]
        logger.info("Built MCP SDK server for project %s", project_id)
    except Exception:
        # No SDK available — the registry is still fully usable.
        logger.debug("MCP SDK not installed; using registry-only server")

    return registry


__all__ = ["MCPServerRegistry", "create_mcp_server"]
