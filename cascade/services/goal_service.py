"""Goal service — strategic objectives with read-time progress aggregation.

Progress is *never* denormalised: when ``auto_aggregate`` is True, the
percentage is computed on every read from the linked tasks' statuses.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.models import Goal, Task
from cascade.schemas import GoalCreate, GoalProgress, GoalUpdate
from cascade.utils import new_id


class GoalService:
    """CRUD + progress aggregation for :class:`Goal`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_goal(self, data: GoalCreate) -> Goal:
        """Create a strategic goal."""
        goal = Goal(
            id=new_id(),
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            metric_name=data.metric_name,
            target_value=data.target_value,
            current_value=0.0,
            auto_aggregate=data.auto_aggregate,
            status=data.status,
            sort_order=data.sort_order,
        )
        self.session.add(goal)
        await self.session.commit()
        await self.session.refresh(goal)
        return goal

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Fetch a single goal."""
        result = await self.session.execute(
            select(Goal).where(Goal.id == goal_id)
        )
        return result.scalar_one_or_none()

    async def list_goals(self, project_id: str) -> list[Goal]:
        """List goals for a project ordered by sort_order."""
        result = await self.session.execute(
            select(Goal)
            .where(Goal.project_id == project_id)
            .order_by(Goal.sort_order, Goal.created_at)
        )
        return list(result.scalars().all())

    async def update_goal(self, goal_id: str, data: GoalUpdate) -> Goal | None:
        """Partially update a goal."""
        goal = await self.get_goal(goal_id)
        if goal is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(goal, key, value)
        await self.session.commit()
        await self.session.refresh(goal)
        return goal

    async def delete_goal(self, goal_id: str) -> bool:
        """Delete a goal (unlinking tasks)."""
        goal = await self.get_goal(goal_id)
        if goal is None:
            return False
        await self.session.execute(
            update(Task).where(Task.goal_id == goal_id).values(goal_id=None)
        )
        await self.session.delete(goal)
        await self.session.commit()
        return True

    # ------------------------------------------------ PROGRESS (read-time)
    async def _task_counts(self, goal_id: str) -> tuple[int, int]:
        """Return (total, completed) task counts linked to the goal."""
        total_row = await self.session.execute(
            select(func.count()).select_from(Task).where(Task.goal_id == goal_id)
        )
        completed_row = await self.session.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.goal_id == goal_id, Task.status == "completed")
        )
        return total_row.scalar_one(), completed_row.scalar_one()

    async def get_progress(self, goal_id: str) -> GoalProgress | None:
        """Compute the read-time progress for a single goal."""
        goal = await self.get_goal(goal_id)
        if goal is None:
            return None

        total, completed = await self._task_counts(goal_id)
        if goal.auto_aggregate:
            current = float(completed)
        else:
            current = goal.current_value

        target = goal.target_value if goal.target_value else 0
        percentage = (current / target * 100.0) if target else (100.0 if current else 0.0)
        percentage = round(min(max(percentage, 0.0), 100.0), 2)

        return GoalProgress(
            id=goal.id,
            title=goal.title,
            metric_name=goal.metric_name,
            target_value=target,
            current_value=current,
            percentage=percentage,
            task_total=total,
            task_completed=completed,
            status=goal.status,
        )

    async def get_project_goals_summary(self, project_id: str) -> list[GoalProgress]:
        """List every goal's computed progress for a project."""
        goals = await self.list_goals(project_id)
        summaries: list[GoalProgress] = []
        for goal in goals:
            progress = await self.get_progress(goal.id)
            if progress:
                summaries.append(progress)
        return summaries
