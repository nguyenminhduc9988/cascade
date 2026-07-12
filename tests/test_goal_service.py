"""Tests for GoalService — read-time progress aggregation."""

from __future__ import annotations

import pytest

from cascade.models import Project
from cascade.schemas.goal import GoalCreate
from cascade.schemas.task import TaskCreate
from cascade.services.goal_service import GoalService
from cascade.services.task_service import TaskService


async def _project(session) -> Project:
    project = Project(id="01PROJECT0000000000000000002", name="Goals")
    session.add(project)
    await session.commit()
    return project


@pytest.mark.asyncio
async def test_progress_aggregates_from_linked_tasks(session):
    project = await _project(session)
    goal_svc = GoalService(session)
    task_svc = TaskService(session)

    goal = await goal_svc.create_goal(
        GoalCreate(project_id=project.id, title="Ship MVP", target_value=2.0)
    )
    t1 = await task_svc.create_task(
        TaskCreate(project_id=project.id, title="t1", goal_id=goal.id)
    )
    t2 = await task_svc.create_task(
        TaskCreate(project_id=project.id, title="t2", goal_id=goal.id)
    )

    progress = await goal_svc.get_progress(goal.id)
    assert progress.task_total == 2
    assert progress.task_completed == 0
    assert progress.percentage == 0.0

    await task_svc.update_status(t1.id, "ongoing")
    await task_svc.update_status(t1.id, "completed")

    progress = await goal_svc.get_progress(goal.id)
    assert progress.task_completed == 1
    assert progress.percentage == 50.0


@pytest.mark.asyncio
async def test_progress_summary_for_project(session):
    project = await _project(session)
    goal_svc = GoalService(session)
    task_svc = TaskService(session)
    goal = await goal_svc.create_goal(
        GoalCreate(project_id=project.id, title="G", target_value=1.0)
    )
    t = await task_svc.create_task(
        TaskCreate(project_id=project.id, title="t", goal_id=goal.id)
    )
    await task_svc.update_status(t.id, "ongoing")
    await task_svc.update_status(t.id, "completed")

    summary = await goal_svc.get_project_goals_summary(project.id)
    assert len(summary) == 1
    assert summary[0].percentage == 100.0
    assert summary[0].status != "abandoned"


@pytest.mark.asyncio
async def test_manual_goal_progress(session):
    project = await _project(session)
    goal_svc = GoalService(session)
    goal = await goal_svc.create_goal(
        GoalCreate(
            project_id=project.id,
            title="Manual",
            target_value=100.0,
            auto_aggregate=False,
        )
    )
    from cascade.schemas.goal import GoalUpdate

    await goal_svc.update_goal(goal.id, GoalUpdate(current_value=25.0))
    progress = await goal_svc.get_progress(goal.id)
    assert progress.percentage == 25.0
