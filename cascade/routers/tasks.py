"""Task REST endpoints — /api/tasks (CRUD + dequeue + status transitions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.database import get_db
from cascade.models import Task
from cascade.schemas import (
    MessageCreate,
    MessageResponse,
    TaskCreate,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
)
from cascade.services.task_service import TaskService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _service(session: AsyncSession = Depends(get_db)) -> TaskService:
    return TaskService(session)


async def serialize_task(task: Task, svc: TaskService, full: bool = False) -> dict:
    """Build a TaskResponse dict, enriching with dependency state when ``full``."""
    data = {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "type": task.type,
        "status": task.status,
        "created_by": task.created_by,
        "assignee": task.assignee,
        "parent_id": task.parent_id,
        "goal_id": task.goal_id,
        "milestone_id": task.milestone_id,
        "priority": task.priority,
        "sort_order": task.sort_order,
        "story_points": task.story_points,
        "estimated_hours": task.estimated_hours,
        "cron_schedule": task.cron_schedule,
        "cron_template_id": task.cron_template_id,
        "emit_event_id": task.emit_event_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "dependencies_ready": False,
        "depends_on": [],
        "blocks": [],
        "messages": [],
    }

    if full:
        deps = await svc.get_dependencies(task.id)
        data["depends_on"] = [d["task_id"] for d in deps.get("depends_on", [])]
        data["blocks"] = [b["task_id"] for b in deps.get("blocks", [])]
        data["dependencies_ready"] = deps.get("all_deps_completed", False)
        messages = await svc.list_messages(task.id)
        data["messages"] = [MessageResponse.model_validate(m) for m in messages]
    return data


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, svc: TaskService = Depends(_service)):
    """Create a task (agent or human), optionally with dependencies."""
    try:
        task = await svc.create_task(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await serialize_task(task, svc, full=False)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    project_id: str = Query(...),
    status_filter: str | None = Query(None, alias="status"),
    goal_id: str | None = None,
    milestone_id: str | None = None,
    parent_id: str | None = None,
    svc: TaskService = Depends(_service),
):
    """List tasks for a project with optional filters."""
    tasks = await svc.get_tasks_by_project(
        project_id,
        status=status_filter,
        goal_id=goal_id,
        milestone_id=milestone_id,
        parent_id=parent_id,
    )
    return [await serialize_task(t, svc) for t in tasks]


@router.get("/dequeue", response_model=TaskResponse | None)
async def dequeue_next_task(
    project_id: str = Query(...),
    assignee: str = Query("agent"),
    svc: TaskService = Depends(_service),
):
    """DEQUEUE the next ready task for an agent (pull-based work queue)."""
    task = await svc.get_next_task(project_id, assignee=assignee)
    if task is None:
        return None
    return await serialize_task(task, svc)


@router.get("/ready", response_model=list[TaskResponse])
async def list_ready_tasks(
    project_id: str = Query(...), svc: TaskService = Depends(_service)
):
    """List not_started tasks whose dependencies are all completed."""
    tasks = await svc.get_ready_tasks(project_id)
    return [await serialize_task(t, svc) for t in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, svc: TaskService = Depends(_service)):
    """Fetch a single task with full conversation + dependency context."""
    task = await svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return await serialize_task(task, svc, full=True)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str, data: TaskUpdate, svc: TaskService = Depends(_service)
):
    """Update task metadata (not status — use the status endpoint)."""
    task = await svc.update_task(task_id, data)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return await serialize_task(task, svc)


@router.patch("/{task_id}/status", response_model=TaskResponse)
async def update_status(
    task_id: str,
    payload: TaskStatusUpdate,
    actor: str = Query("agent"),
    svc: TaskService = Depends(_service),
):
    """Transition a task's status through the state machine."""
    try:
        task = await svc.update_status(
            task_id, payload.status, reason=payload.reason, actor=actor
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await serialize_task(task, svc)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, svc: TaskService = Depends(_service)):
    """Delete a task."""
    if not await svc.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")


@router.get("/{task_id}/dependencies")
async def get_dependencies(task_id: str, svc: TaskService = Depends(_service)):
    """Return the dependency tree (depends_on / blocks) for a task."""
    if await svc.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return await svc.get_dependencies(task_id)


@router.post("/{task_id}/messages", response_model=MessageResponse)
async def add_message(
    task_id: str, data: MessageCreate, svc: TaskService = Depends(_service)
):
    """Append a message to the task conversation log."""
    if await svc.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = data.model_dump()
    payload["task_id"] = task_id
    return await svc.add_message(
        task_id=task_id,
        author=payload["author"],
        content=payload["content"],
        message_type=payload["message_type"],
        metadata=loads_payload(payload["metadata_json"]),
    )


@router.get("/{task_id}/messages", response_model=list[MessageResponse])
async def list_messages(task_id: str, svc: TaskService = Depends(_service)):
    """Return the full conversation log for a task."""
    if await svc.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return await svc.list_messages(task_id)


def loads_payload(raw: str | None) -> dict | None:
    """Parse an optional JSON metadata string into a dict."""
    if not raw:
        return None
    from cascade.utils import loads

    return loads(raw)
