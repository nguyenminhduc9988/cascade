"""Scheduler service — cron template → instance spawning with idempotency.

Called every 60s by APScheduler. For each ``cron``-status task:
1. Parse ``cron_schedule`` with croniter.
2. If the next run is due AND no active child exists → clone a child.
3. One-time templates (``@once``) are deleted after spawning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.models import Task
from cascade.utils import new_id

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("not_started", "ongoing")


class SchedulerService:
    """Spawns task instances from cron templates idempotently."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def process_cron_templates(self) -> list[Task]:
        """Process every due cron template, returning spawned children."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(Task).where(
                Task.status == "cron", Task.cron_schedule.is_not(None)
            )
        )
        spawned: list[Task] = []
        for template in result.scalars().all():
            try:
                child = await self._maybe_spawn(template, now)
            except Exception:  # pragma: no cover - defensive per-template
                logger.exception("Failed to process cron template %s", template.id)
                child = None
            if child is not None:
                spawned.append(child)
        if spawned:
            await self.session.commit()
        return spawned

    async def _maybe_spawn(
        self, template: Task, now: datetime
    ) -> Task | None:
        """Spawn a child for a template if due and no active child exists."""
        # Idempotency: never spawn while an active child exists.
        active = await self.session.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.cron_template_id == template.id,
                Task.status.in_(ACTIVE_STATUSES),
            )
        )
        if active.scalar_one() > 0:
            return None

        # Determine the anchor time for "next run" (most recent child or template).
        last_row = await self.session.execute(
            select(func.max(Task.created_at)).where(
                Task.cron_template_id == template.id
            )
        )
        last_dt = last_row.scalar_one_or_none()
        anchor = _to_utc(last_dt) if last_dt else _to_utc(template.created_at)

        if template.cron_schedule == "@once":
            # One-time template: spawn immediately on first due check.
            child = self._clone(template)
            self.session.add(child)
            await self.session.delete(template)  # one-time → delete after spawn
            return child

        try:
            cron = croniter(template.cron_schedule, anchor)
            next_run = cron.get_next(datetime).astimezone(timezone.utc)
        except Exception:
            logger.warning("Invalid cron schedule %r", template.cron_schedule)
            return None

        if next_run > now:
            return None

        child = self._clone(template)
        self.session.add(child)
        return child

    def _clone(self, template: Task) -> Task:
        """Clone a template into a fresh ``not_started`` child task."""
        return Task(
            id=new_id(),
            project_id=template.project_id,
            title=template.title,
            description=template.description,
            type=template.type,
            status="not_started",
            created_by="agent",
            assignee=template.assignee,
            parent_id=template.id,
            cron_template_id=template.id,
            goal_id=template.goal_id,
            milestone_id=template.milestone_id,
            priority=template.priority,
            story_points=template.story_points,
            estimated_hours=template.estimated_hours,
        )


def _to_utc(value: datetime) -> datetime:
    """Normalise a datetime to aware UTC for cron iteration."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
