"""Dashboard endpoints — SSE stream + aggregate big-picture views."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from cascade.database import get_db
from cascade.engine.progress_tracker import tracker
from cascade.services.goal_service import GoalService
from cascade.services.milestone_service import MilestoneService
from cascade.services.monitor_service import MonitorService
from cascade.services.project_service import ProjectService
from cascade.services.task_service import TaskService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/sse/{project_id}")
async def sse_stream(project_id: str, request: Request):
    """Server-Sent Events stream for a project.

    Emits ``task_created``, ``status_change``, ``message`` and ``progress``
    events as they happen. Closes when the client disconnects.
    """

    async def event_generator():
        # ``tracker.stream`` blocks indefinitely on the subscriber queue
        # between events, so checking ``is_disconnected()`` only after a
        # yield would leave the generator (and its queue subscription)
        # hanging forever whenever a disconnected client falls silent.
        # Poll with a timeout instead, sending a keep-alive ping when idle.
        stream = tracker.stream(project_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(stream.__anext__(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                except StopAsyncIteration:
                    break
                yield {
                    "event": message["event"],
                    "data": json.dumps(message["data"], default=str),
                }
        finally:
            await stream.aclose()

    return EventSourceResponse(event_generator())


async def _build_project_view(project_id: str, session: AsyncSession) -> dict:
    """Assemble the full dashboard aggregate for a single project."""
    project_svc = ProjectService(session)
    goal_svc = GoalService(session)
    milestone_svc = MilestoneService(session)
    task_svc = TaskService(session)
    monitor_svc = MonitorService(session)

    project = await project_svc.get_project(project_id)
    goals = await goal_svc.get_project_goals_summary(project_id)
    milestones = await milestone_svc.list_with_rollup(project_id)
    stalled = await monitor_svc.get_stalled_tasks(project_id)
    agent_alive = await monitor_svc.is_agent_alive(project_id)
    live_projects = await monitor_svc.live_projects()
    activity = await monitor_svc.recent_activity(project_id, limit=10)

    tasks = await task_svc.get_tasks_by_project(project_id)
    status_counts: dict[str, int] = {}
    for t in tasks:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "mission": project.mission,
            "status": project.status,
        }
        if project
        else None,
        "agent_alive": agent_alive,
        "live_sessions": live_projects.get(project_id, 0),
        "goals": [g.model_dump() for g in goals],
        "milestones": [m.model_dump() for m in milestones],
        "stalled_tasks": [
            {"id": t.id, "title": t.title, "status": t.status} for t in stalled
        ],
        "task_status_counts": status_counts,
        "recent_activity": [
            {
                "id": a.id,
                "action": a.action,
                "actor": a.actor,
                "task_id": a.task_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activity
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/aggregate")
async def project_aggregate(project_id: str, session: AsyncSession = Depends(get_db)):
    """Return the full dashboard aggregate for one project."""
    return await _build_project_view(project_id, session)


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_db)):
    """Return a lightweight overview of every project + live agents."""
    project_svc = ProjectService(session)
    monitor_svc = MonitorService(session)
    projects = await project_svc.list_projects()
    live = await monitor_svc.live_projects()
    overview = []
    for p in projects:
        overview.append(
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "mission": p.mission,
                "agent_alive": (p.id in live),
                "live_sessions": live.get(p.id, 0),
            }
        )
    return {"projects": overview, "live_project_count": len(live)}


@router.post("/agents/{project_id}/register")
async def register_agent(
    project_id: str, session_id: str, session: AsyncSession = Depends(get_db)
):
    """Register a live agent connection (sets the dashboard green dot)."""
    monitor = MonitorService(session)
    await monitor.register_agent_session(project_id, session_id)
    await tracker.publish(
        project_id, "agent_status", {"alive": True, "session_id": session_id}
    )
    return {"registered": True, "project_id": project_id, "session_id": session_id}


@router.post("/agents/{project_id}/heartbeat")
async def heartbeat(
    project_id: str, session_id: str, session: AsyncSession = Depends(get_db)
):
    """Refresh an agent session's last-seen timestamp."""
    monitor = MonitorService(session)
    await monitor.heartbeat(project_id, session_id)
    return {"ok": True}


async def broadcast_dashboard_tick() -> None:
    """Periodic heartbeat broadcast used by the monitoring loop."""
    await asyncio.sleep(0)
