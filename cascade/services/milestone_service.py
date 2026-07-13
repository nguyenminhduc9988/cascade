"""Milestone service — time-boxed groupings with progress rollup."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.models import Milestone, Task
from cascade.schemas import MilestoneCreate, MilestoneResponse, MilestoneUpdate
from cascade.utils import new_id


class MilestoneService:
    """CRUD + progress rollup for :class:`Milestone`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_milestone(self, data: MilestoneCreate) -> Milestone:
        """Create a new milestone."""
        milestone = Milestone(
            id=new_id(),
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
            status=data.status,
            sort_order=data.sort_order,
        )
        self.session.add(milestone)
        await self.session.commit()
        await self.session.refresh(milestone)
        return milestone

    async def get_milestone(self, milestone_id: str) -> Milestone | None:
        """Fetch a single milestone."""
        result = await self.session.execute(
            select(Milestone).where(Milestone.id == milestone_id)
        )
        return result.scalar_one_or_none()

    async def list_milestones(self, project_id: str) -> list[Milestone]:
        """List milestones for a project."""
        result = await self.session.execute(
            select(Milestone)
            .where(Milestone.project_id == project_id)
            .order_by(Milestone.sort_order, Milestone.created_at)
        )
        return list(result.scalars().all())

    async def update_milestone(
        self, milestone_id: str, data: MilestoneUpdate
    ) -> Milestone | None:
        """Partially update a milestone."""
        milestone = await self.get_milestone(milestone_id)
        if milestone is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(milestone, key, value)
        await self.session.commit()
        await self.session.refresh(milestone)
        return milestone

    async def delete_milestone(self, milestone_id: str) -> bool:
        """Delete a milestone (unlinking tasks)."""
        milestone = await self.get_milestone(milestone_id)
        if milestone is None:
            return False
        await self.session.execute(
            update(Task).where(Task.milestone_id == milestone_id).values(milestone_id=None)
        )
        await self.session.delete(milestone)
        await self.session.commit()
        return True

    async def _rollup(self, milestone_id: str) -> tuple[int, int]:
        """Return (total, completed) task counts linked to the milestone."""
        total_row = await self.session.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.milestone_id == milestone_id)
        )
        completed_row = await self.session.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.milestone_id == milestone_id, Task.status == "completed"
            )
        )
        return total_row.scalar_one(), completed_row.scalar_one()

    async def get_milestone_with_rollup(
        self, milestone_id: str
    ) -> MilestoneResponse | None:
        """Return a milestone response including computed progress."""
        milestone = await self.get_milestone(milestone_id)
        if milestone is None:
            return None
        total, completed = await self._rollup(milestone_id)
        pct = round((completed / total * 100.0) if total else 0.0, 2)
        return MilestoneResponse(
            id=milestone.id,
            project_id=milestone.project_id,
            title=milestone.title,
            description=milestone.description,
            start_date=milestone.start_date,
            end_date=milestone.end_date,
            status=milestone.status,
            sort_order=milestone.sort_order,
            created_at=milestone.created_at,
            task_total=total,
            task_completed=completed,
            progress_percentage=pct,
        )

    async def list_with_rollup(self, project_id: str) -> list[MilestoneResponse]:
        """List milestones for a project with computed progress."""
        milestones = await self.list_milestones(project_id)
        results: list[MilestoneResponse] = []
        for ms in milestones:
            rolled = await self.get_milestone_with_rollup(ms.id)
            if rolled:
                results.append(rolled)
        return results
