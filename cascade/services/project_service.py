"""Project service — CRUD for the coherence anchor."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.models import Project
from cascade.schemas import ProjectCreate, ProjectUpdate
from cascade.utils import new_id


class ProjectService:
    """CRUD operations for :class:`Project`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_project(self, data: ProjectCreate) -> Project:
        """Create a new project with an auto-generated ULID."""
        project = Project(
            id=new_id(),
            name=data.name,
            description=data.description,
            mission=data.mission,
            status=data.status,
        )
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def get_project(self, project_id: str) -> Project | None:
        """Fetch a single project by ID."""
        result = await self.session.execute(
            select(Project).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def list_projects(self, status: str | None = None) -> list[Project]:
        """List projects, optionally filtered by status."""
        stmt = select(Project).order_by(Project.created_at.desc())
        if status:
            stmt = stmt.where(Project.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_project(
        self, project_id: str, data: ProjectUpdate
    ) -> Project | None:
        """Partially update a project."""
        project = await self.get_project(project_id)
        if project is None:
            return None
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(project, key, value)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project (cascades to goals, milestones, tasks)."""
        project = await self.get_project(project_id)
        if project is None:
            return False
        await self.session.delete(project)
        await self.session.commit()
        return True

    async def get_mission(self, project_id: str) -> dict | None:
        """Return the project mission + high-level state for agents."""
        project = await self.get_project(project_id)
        if project is None:
            return None
        return {
            "project_id": project.id,
            "name": project.name,
            "mission": project.mission,
            "status": project.status,
        }
