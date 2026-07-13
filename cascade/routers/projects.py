"""Project REST endpoints — /api/projects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.database import get_db
from cascade.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from cascade.services.project_service import ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _service(session: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(session)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, svc: ProjectService = Depends(_service)):
    """Create a new project."""
    return await svc.create_project(data)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    status_filter: str | None = None, svc: ProjectService = Depends(_service)
):
    """List all projects, optionally filtered by status."""
    return await svc.list_projects(status=status_filter)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, svc: ProjectService = Depends(_service)):
    """Fetch a single project."""
    project = await svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, data: ProjectUpdate, svc: ProjectService = Depends(_service)
):
    """Update a project."""
    project = await svc.update_project(project_id, data)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, svc: ProjectService = Depends(_service)):
    """Delete a project (cascades to children)."""
    if not await svc.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/{project_id}/mission")
async def get_mission(project_id: str, svc: ProjectService = Depends(_service)):
    """Return the project mission brief for agent big-picture context."""
    mission = await svc.get_mission(project_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return mission
