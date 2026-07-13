"""Tests for MilestoneService — progress rollup and deletion unlinking."""

from __future__ import annotations

import pytest

from cascade.models import Project
from cascade.schemas.milestone import MilestoneCreate
from cascade.schemas.task import TaskCreate
from cascade.services.milestone_service import MilestoneService
from cascade.services.task_service import TaskService


async def _project(session) -> Project:
    project = Project(id="01PROJECT0000000000000000005", name="Milestones")
    session.add(project)
    await session.commit()
    return project


@pytest.mark.asyncio
async def test_rollup_reflects_task_completion(session):
    project = await _project(session)
    ms_svc = MilestoneService(session)
    task_svc = TaskService(session)

    ms = await ms_svc.create_milestone(
        MilestoneCreate(project_id=project.id, title="Beta launch")
    )
    task = await task_svc.create_task(
        TaskCreate(project_id=project.id, title="t", milestone_id=ms.id)
    )
    rolled = await ms_svc.get_milestone_with_rollup(ms.id)
    assert rolled.task_total == 1
    assert rolled.task_completed == 0

    await task_svc.update_status(task.id, "ongoing")
    await task_svc.update_status(task.id, "completed")

    rolled = await ms_svc.get_milestone_with_rollup(ms.id)
    assert rolled.task_completed == 1
    assert rolled.progress_percentage == 100.0


@pytest.mark.asyncio
async def test_delete_milestone_unlinks_tasks(session):
    project = await _project(session)
    ms_svc = MilestoneService(session)
    task_svc = TaskService(session)
    ms = await ms_svc.create_milestone(
        MilestoneCreate(project_id=project.id, title="Beta launch")
    )
    task = await task_svc.create_task(
        TaskCreate(project_id=project.id, title="t", milestone_id=ms.id)
    )

    assert await ms_svc.delete_milestone(ms.id) is True

    refetched = await task_svc.get_task(task.id)
    assert refetched is not None
    assert refetched.milestone_id is None
