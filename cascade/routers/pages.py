"""HTMX page routes — server-rendered UI (/, /projects/{id}, /tasks/{id}).

These routes return full Jinja2 templates that rely on HTMX to swap fragments
without full page reloads, and an SSE client for real-time updates.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.database import get_db
from cascade.services.goal_service import GoalService
from cascade.services.milestone_service import MilestoneService
from cascade.services.monitor_service import MonitorService
from cascade.services.project_service import ProjectService
from cascade.services.task_service import TaskService

router = APIRouter(tags=["pages"])

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


@router.get("/")
async def dashboard_page(request: Request, session: AsyncSession = Depends(get_db)):
    """Big-picture dashboard: all projects with goal progress + agent status."""
    project_svc = ProjectService(session)
    monitor_svc = MonitorService(session)
    projects = await project_svc.list_projects()
    live = await monitor_svc.live_projects()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "projects": projects,
            "live_projects": live,
            "first_project_id": projects[0].id if projects else None,
        },
    )


@router.get("/projects/{project_id}")
async def project_page(
    request: Request, project_id: str, session: AsyncSession = Depends(get_db)
):
    """Project detail: goals, milestones and a Kanban board."""
    project_svc = ProjectService(session)
    goal_svc = GoalService(session)
    milestone_svc = MilestoneService(session)
    task_svc = TaskService(session)

    project = await project_svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    goals = await goal_svc.get_project_goals_summary(project_id)
    milestones = await milestone_svc.list_with_rollup(project_id)
    tasks = await task_svc.get_tasks_by_project(project_id)

    columns = {
        "not_started": [t for t in tasks if t.status == "not_started"],
        "ongoing": [t for t in tasks if t.status == "ongoing"],
        "blocked": [t for t in tasks if t.status == "blocked"],
        "completed": [t for t in tasks if t.status == "completed"],
    }
    return templates.TemplateResponse(
        request,
        "project.html",
        {
            "project": project,
            "goals": goals,
            "milestones": milestones,
            "columns": columns,
        },
    )


@router.get("/tasks/{task_id}")
async def task_page(
    request: Request, task_id: str, session: AsyncSession = Depends(get_db)
):
    """Task detail: full conversation, status, dependencies, coherence links."""
    task_svc = TaskService(session)
    monitor_svc = MonitorService(session)

    task = await task_svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    messages = await task_svc.list_messages(task_id)
    deps = await task_svc.get_dependencies(task_id)
    completion = await monitor_svc.check_completion(task_id)
    children = [
        {"id": c.id, "title": c.title, "status": c.status}
        for c in (task.children or [])
    ]
    return templates.TemplateResponse(
        request,
        "task.html",
        {
            "task": task,
            "messages": messages,
            "dependencies": deps,
            "completion_verified": completion,
            "children": children,
        },
    )


@router.get("/board/{project_id}")
async def board_page(
    request: Request, project_id: str, session: AsyncSession = Depends(get_db)
):
    """Standalone Kanban board view."""
    project_svc = ProjectService(session)
    task_svc = TaskService(session)
    project = await project_svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    tasks = await task_svc.get_tasks_by_project(project_id)
    columns = {
        "not_started": [t for t in tasks if t.status == "not_started"],
        "ongoing": [t for t in tasks if t.status == "ongoing"],
        "blocked": [t for t in tasks if t.status == "blocked"],
        "completed": [t for t in tasks if t.status == "completed"],
    }
    return templates.TemplateResponse(
        request,
        "board.html",
        {"project": project, "columns": columns},
    )


@router.get("/partials/project_aggregate/{project_id}")
async def project_aggregate_partial(
    request: Request, project_id: str, session: AsyncSession = Depends(get_db)
):
    """HTMX partial: goals + task status counts for the dashboard card."""
    from cascade.routers.dashboard import _build_project_view

    view = await _build_project_view(project_id, session)
    return templates.TemplateResponse(
        request,
        "partials/project_aggregate.html",
        {
            "goals": view["goals"],
            "task_status_counts": view["task_status_counts"],
            "stalled_tasks": view["stalled_tasks"],
        },
    )
