"""Tests for SchedulerService — cron template spawning idempotency."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cascade.models import Project, Task
from cascade.schemas.task import TaskCreate
from cascade.services.scheduler_service import SchedulerService
from cascade.services.task_service import TaskService


async def _project(session) -> Project:
    project = Project(id="01PROJECT0000000000000000002", name="Test")
    session.add(project)
    await session.commit()
    return project


@pytest.mark.asyncio
async def test_once_template_spawns_without_violating_referential_integrity(session):
    """A ``@once`` template's child FKs back to it — spawning must not delete
    the template row out from under those foreign keys."""
    project = await _project(session)
    task_svc = TaskService(session)
    template = await task_svc.create_task(
        TaskCreate(
            project_id=project.id, title="onboarding", status="cron", cron_schedule="@once"
        )
    )

    scheduler = SchedulerService(session)
    spawned = await scheduler.process_cron_templates()

    assert len(spawned) == 1
    child = spawned[0]
    assert child.parent_id == template.id
    assert child.cron_template_id == template.id

    # The template row must still exist (referential integrity intact) but
    # is cleared so it's never selected again.
    refetched = await session.get(Task, template.id)
    assert refetched is not None
    assert refetched.cron_schedule is None

    # A second tick must not spawn a duplicate.
    spawned_again = await scheduler.process_cron_templates()
    assert spawned_again == []


@pytest.mark.asyncio
async def test_once_template_does_not_respawn_after_child_completes(session):
    project = await _project(session)
    task_svc = TaskService(session)
    template = await task_svc.create_task(
        TaskCreate(
            project_id=project.id, title="setup", status="cron", cron_schedule="@once"
        )
    )

    scheduler = SchedulerService(session)
    spawned = await scheduler.process_cron_templates()
    child = spawned[0]

    await task_svc.update_status(child.id, "ongoing")
    await task_svc.update_status(child.id, "completed")

    spawned_again = await scheduler.process_cron_templates()
    assert spawned_again == []

    result = await session.execute(
        select(Task).where(Task.cron_template_id == template.id)
    )
    assert len(result.scalars().all()) == 1
