"""Project service — CRUD for the coherence anchor."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.models import Project, Task, Telemetry
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
        """Delete a project (cascades to goals, milestones, tasks, events).

        The self-referential ``parent_id``/``cron_template_id`` links between
        a project's own tasks are cleared first: ORM cascade-delete of the
        ``tasks`` collection issues per-row DELETEs without resolving that
        same-table ordering, which trips ``PRAGMA foreign_keys=ON`` whenever
        a task is deleted before the child/clone still pointing at it. The
        immutable :class:`~cascade.models.telemetry.Telemetry` audit trail is
        unlinked the same way rather than deleted. Every mutation here is an
        ORM attribute assignment (not a raw bulk ``UPDATE``) so the unit of
        work orders these UPDATEs ahead of the cascade DELETEs.
        """
        project = await self.get_project(project_id)
        if project is None:
            return False
        tasks = await self.session.execute(
            select(Task).where(Task.project_id == project_id)
        )
        task_ids = []
        for task in tasks.scalars().all():
            task.parent_id = None
            task.cron_template_id = None
            task_ids.append(task.id)

        telemetry_filter = Telemetry.project_id == project_id
        if task_ids:
            telemetry_filter = or_(telemetry_filter, Telemetry.task_id.in_(task_ids))
        telemetry_rows = await self.session.execute(
            select(Telemetry).where(telemetry_filter)
        )
        for record in telemetry_rows.scalars().all():
            record.project_id = None
            record.task_id = None

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
