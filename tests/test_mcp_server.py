"""Tests for MCPServerRegistry — per-workspace scoping."""

from __future__ import annotations

import pytest

from cascade.mcp.server import create_mcp_server
from cascade.models import Project
from cascade.services.project_service import ProjectService
from cascade.services.task_service import TaskService
from cascade.schemas.project import ProjectCreate
from cascade.schemas.task import TaskCreate


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


@pytest.mark.asyncio
async def test_task_id_tools_reject_foreign_project_task(session):
    """A task_id borrowed from another workspace must be rejected, not served/mutated."""
    project_svc = ProjectService(session)
    home = await project_svc.create_project(ProjectCreate(name="Home"))
    other = await project_svc.create_project(ProjectCreate(name="Other"))

    other_task = await TaskService(session).create_task(
        TaskCreate(title="Secret", description="TOP SECRET DATA", project_id=other.id)
    )

    server = create_mcp_server(home.id)

    for name, extra in [
        ("get_task", {}),
        ("reply", {"content": "hi"}),
        ("update_status", {"status": "ongoing"}),
        ("get_dependencies", {}),
        ("auto_decide", {"choices": [{"label": "a"}]}),
    ]:
        result = await server.call(name, session, task_id=other_task.id, **extra)
        assert result == {"error": "task not found"}, name

    # Confirm no mutation slipped through despite the rejected calls.
    reread = await TaskService(session).get_task(other_task.id)
    assert reread.status == "not_started"
