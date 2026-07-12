"""Goal REST endpoints — /api/goals (CRUD + progress aggregation)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.database import get_db
from cascade.schemas import GoalCreate, GoalProgress, GoalResponse, GoalUpdate
from cascade.services.goal_service import GoalService

router = APIRouter(prefix="/api/goals", tags=["goals"])


def _service(session: AsyncSession = Depends(get_db)) -> GoalService:
    return GoalService(session)


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(data: GoalCreate, svc: GoalService = Depends(_service)):
    """Create a strategic goal."""
    return await svc.create_goal(data)


@router.get("", response_model=list[GoalResponse])
async def list_goals(project_id: str, svc: GoalService = Depends(_service)):
    """List goals for a project."""
    return await svc.list_goals(project_id)


@router.get("/progress", response_model=list[GoalProgress])
async def project_goals_summary(project_id: str, svc: GoalService = Depends(_service)):
    """Compute the read-time progress for every goal in a project."""
    return await svc.get_project_goals_summary(project_id)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: str, svc: GoalService = Depends(_service)):
    """Fetch a single goal."""
    goal = await svc.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@router.get("/{goal_id}/progress", response_model=GoalProgress)
async def get_goal_progress(goal_id: str, svc: GoalService = Depends(_service)):
    """Compute the read-time progress for a single goal."""
    progress = await svc.get_progress(goal_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return progress


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: str, data: GoalUpdate, svc: GoalService = Depends(_service)
):
    """Update a goal."""
    goal = await svc.update_goal(goal_id, data)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(goal_id: str, svc: GoalService = Depends(_service)):
    """Delete a goal."""
    if not await svc.delete_goal(goal_id):
        raise HTTPException(status_code=404, detail="Goal not found")
