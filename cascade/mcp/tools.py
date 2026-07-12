"""MCP tool implementations — the agent-facing API surface.

Each tool is an async function ``tool_name(session, **params)`` returning a
plain dict. They delegate to services so behaviour is identical to the REST
API. The registry in :data:`TOOLS_REGISTRY` maps names → (callable, schema).
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from cascade.schemas.task import TaskCreate
from cascade.services.auto_decision import AutoDecisionService
from cascade.services.event_service import EventService
from cascade.services.goal_service import GoalService
from cascade.services.milestone_service import MilestoneService
from cascade.services.project_service import ProjectService
from cascade.services.task_service import TaskService


# ---------------------------------------------------------------------- TOOLS
async def get_task(
    session: AsyncSession,
    task_id: str | None = None,
    project_id: str | None = None,
    assignee: str = "agent",
) -> dict:
    """Dequeue the next ready task (no ID) or fetch a specific task (with ID).

    When ``task_id`` is omitted this is the pull-based work queue: it returns
    the highest-priority ``not_started`` task whose dependencies are completed.
    """
    task_svc = TaskService(session)
    if task_id:
        task = await task_svc.get_task(task_id)
        if task is None:
            return {"error": "task not found"}
        return {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "project_id": task.project_id,
            "goal_id": task.goal_id,
            "milestone_id": task.milestone_id,
        }
    if not project_id:
        return {"error": "project_id required when task_id is omitted"}
    task = await task_svc.get_next_task(project_id, assignee=assignee)
    if task is None:
        return {"empty": True, "message": "no ready tasks"}
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "project_id": task.project_id,
        "goal_id": task.goal_id,
        "milestone_id": task.milestone_id,
        "priority": task.priority,
    }


async def create_task(
    session: AsyncSession,
    title: str,
    project_id: str,
    description: str | None = None,
    type: str = "task",
    goal_id: str | None = None,
    milestone_id: str | None = None,
    parent_id: str | None = None,
    depends_on: list[str] | None = None,
    priority: int = 0,
    created_by: str = "agent",
) -> dict:
    """Create a task — agents use this to decompose and delegate."""
    task_svc = TaskService(session)
    task = await task_svc.create_task(
        TaskCreate(
            title=title,
            project_id=project_id,
            description=description,
            type=type,
            goal_id=goal_id,
            milestone_id=milestone_id,
            parent_id=parent_id,
            depends_on=depends_on,
            priority=priority,
            created_by=created_by,
        )
    )
    return {"id": task.id, "title": task.title, "status": task.status}


async def reply(
    session: AsyncSession,
    task_id: str,
    content: str,
    message_type: str = "progress",
    author: str = "agent",
) -> dict:
    """Send a progress/reply/ask message to a task's conversation log."""
    task_svc = TaskService(session)
    msg = await task_svc.add_message(
        task_id=task_id,
        author=author,
        content=content,
        message_type=message_type,
    )
    return {"id": msg.id, "task_id": task_id, "message_type": message_type}


async def update_status(
    session: AsyncSession, task_id: str, status: str, reason: str | None = None
) -> dict:
    """Transition a task's status through the state machine."""
    task_svc = TaskService(session)
    try:
        task = await task_svc.update_status(task_id, status, reason=reason, actor="agent")
    except ValueError as exc:
        return {"error": str(exc)}
    return {"id": task.id, "status": task.status}


async def get_mission(session: AsyncSession, project_id: str) -> dict:
    """Return the project mission + active goals + milestones (big picture)."""
    project_svc = ProjectService(session)
    goal_svc = GoalService(session)
    mission = await project_svc.get_mission(project_id)
    if mission is None:
        return {"error": "project not found"}
    goals = await goal_svc.get_project_goals_summary(project_id)
    mission["goals"] = [g.model_dump() for g in goals]
    return mission


async def get_project_context(session: AsyncSession, project_id: str) -> dict:
    """Return the full project state for strategic coherence.

    Includes goals with progress, milestones, and the task tree so the agent
    understands how its work fits the big picture.
    """
    goal_svc = GoalService(session)
    milestone_svc = MilestoneService(session)
    task_svc = TaskService(session)

    goals = await goal_svc.get_project_goals_summary(project_id)
    milestones = await milestone_svc.list_with_rollup(project_id)
    tasks = await task_svc.get_tasks_by_project(project_id)
    task_tree: list[dict] = []
    by_parent: dict[str | None, list] = {}
    for t in tasks:
        by_parent.setdefault(t.parent_id, []).append(t)
    for t in by_parent.get(None, []):
        task_tree.append(
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "type": t.type,
                "goal_id": t.goal_id,
            }
        )
    return {
        "project_id": project_id,
        "goals": [g.model_dump() for g in goals],
        "milestones": [m.model_dump() for m in milestones],
        "task_tree": task_tree,
        "task_count": len(tasks),
    }


async def publish_event(
    session: AsyncSession,
    project_id: str,
    event_name: str,
    payload: dict | None = None,
) -> dict:
    """Emit an event for cross-project choreography (fires triggers)."""
    event_svc = EventService(session)
    from cascade.schemas.event import EventPublish

    return await event_svc.publish_event(
        EventPublish(project_id=project_id, name=event_name, payload=payload)
    )


async def get_dependencies(session: AsyncSession, task_id: str) -> dict:
    """Return a task's dependency tree status (what it waits on / blocks)."""
    task_svc = TaskService(session)
    return await task_svc.get_dependencies(task_id)


async def auto_decide(
    session: AsyncSession, task_id: str, choices: list[dict]
) -> dict:
    """Auto-resolve a choice without human intervention (autonomy helper)."""
    svc = AutoDecisionService(session)
    return await svc.auto_resolve_choice(task_id, choices)


# --------------------------------------------------------------- REGISTRY
ToolCallable = Callable[..., Any]

TOOLS_REGISTRY: dict[str, dict[str, Any]] = {
    "get_task": {"fn": get_task, "description": "Dequeue next task or fetch by ID"},
    "create_task": {"fn": create_task, "description": "Create a (sub)task or delegate"},
    "reply": {"fn": reply, "description": "Send a progress/reply message"},
    "update_status": {"fn": update_status, "description": "Transition task status"},
    "get_mission": {"fn": get_mission, "description": "Big-picture mission + goals"},
    "get_project_context": {"fn": get_project_context, "description": "Full project state"},
    "publish_event": {"fn": publish_event, "description": "Emit a choreography event"},
    "get_dependencies": {"fn": get_dependencies, "description": "Dependency tree status"},
    "auto_decide": {"fn": auto_decide, "description": "Auto-resolve a choice"},
}

# Flat list of tool callables for convenience.
MCP_TOOLS: dict[str, ToolCallable] = {name: spec["fn"] for name, spec in TOOLS_REGISTRY.items()}

__all__ = ["TOOLS_REGISTRY", "MCP_TOOLS"]
