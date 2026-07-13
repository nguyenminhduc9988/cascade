"""Tests for MCPServerRegistry — per-workspace scoping."""

from __future__ import annotations

import pytest

from cascade.mcp.server import create_mcp_server
from cascade.models import Project
from cascade.services.project_service import ProjectService
from cascade.schemas.project import ProjectCreate


@pytest.mark.asyncio
async def test_call_forces_own_workspace_project_id(session):
    """A workspace-scoped MCP server must never let a caller act on another project."""
    project_svc = ProjectService(session)
    home = await project_svc.create_project(ProjectCreate(name="Home"))
    other = Project(id="01PROJECT0000000000000000006", name="Other")
    session.add(other)
    await session.commit()

    server = create_mcp_server(home.id)

    # Caller explicitly tries to target a different project — must be ignored.
    result = await server.call(
        "get_mission", session, project_id=other.id
    )
    assert result["project_id"] == home.id
    assert result["name"] == "Home"
