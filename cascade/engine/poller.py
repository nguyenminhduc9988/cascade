"""Poller — work distribution + stall nudging.

In Cascade, agents pull work via ``get_task`` (dequeue). The poller therefore
focuses on *push* opportunities that a pull-only model misses: detecting
stalled tasks and nudging them so work never silently stalls.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from cascade.services.monitor_service import MonitorService
from cascade.services.project_service import ProjectService

logger = logging.getLogger(__name__)


async def poller_tick(session: AsyncSession) -> int:
    """Detect stalled tasks across all projects and nudge them.

    Returns the number of tasks nudged.
    """
    project_svc = ProjectService(session)
    monitor_svc = MonitorService(session)
    projects = await project_svc.list_projects(status="active")

    nudged = 0
    for project in projects:
        stalled = await monitor_svc.get_stalled_tasks(project.id)
        for task in stalled:
            await monitor_svc.nudge_stalled_task(task.id)
            nudged += 1
            logger.info("Nudged stalled task %s in project %s", task.id, project.id)
    if nudged:
        await session.commit()
    return nudged
