"""Milestone REST endpoints — /api/milestones (CRUD + progress rollup)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.database import get_db
from cascade.schemas import (
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
)
from cascade.services.milestone_service import MilestoneService

router = APIRouter(prefix="/api/milestones", tags=["milestones"])


def _service(session: AsyncSession = Depends(get_db)) -> MilestoneService:
    return MilestoneService(session)


@router.post("", response_model=MilestoneResponse, status_code=status.HTTP_201_CREATED)
async def create_milestone(data: MilestoneCreate, svc: MilestoneService = Depends(_service)):
    """Create a milestone."""
    milestone = await svc.create_milestone(data)
    return await svc.get_milestone_with_rollup(milestone.id)


@router.get("", response_model=list[MilestoneResponse])
async def list_milestones(project_id: str, svc: MilestoneService = Depends(_service)):
    """List milestones for a project with computed progress."""
    return await svc.list_with_rollup(project_id)


@router.get("/{milestone_id}", response_model=MilestoneResponse)
async def get_milestone(milestone_id: str, svc: MilestoneService = Depends(_service)):
    """Fetch a milestone with progress rollup."""
    milestone = await svc.get_milestone_with_rollup(milestone_id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return milestone


@router.put("/{milestone_id}", response_model=MilestoneResponse)
async def update_milestone(
    milestone_id: str, data: MilestoneUpdate, svc: MilestoneService = Depends(_service)
):
    """Update a milestone."""
    milestone = await svc.update_milestone(milestone_id, data)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return await svc.get_milestone_with_rollup(milestone_id)


@router.delete("/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_milestone(milestone_id: str, svc: MilestoneService = Depends(_service)):
    """Delete a milestone."""
    if not await svc.delete_milestone(milestone_id):
        raise HTTPException(status_code=404, detail="Milestone not found")
