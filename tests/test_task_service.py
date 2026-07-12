"""Tests for TaskService — state machine, dequeue and DAG resolution."""

from __future__ import annotations

import pytest

from cascade.models import Project
from cascade.schemas.task import TaskCreate
from cascade.services.task_service import TaskService


async def _project(session) -> Project:
    project = Project(id="01PROJECT0000000000000000001", name="Test")
    session.add(project)
    await session.commit()
    return project


@pytest.mark.asyncio
async def test_create_and_get_task(session):
    project = await _project(session)
    svc = TaskService(session)
    task = await svc.create_task(
        TaskCreate(project_id=project.id, title="Build feature", type="task")
    )
    fetched = await svc.get_task(task.id)
    assert fetched is not None
    assert fetched.title == "Build feature"
    assert fetched.status == "not_started"


@pytest.mark.asyncio
async def test_status_state_machine_valid_transitions(session):
    project = await _project(session)
    svc = TaskService(session)
    task = await svc.create_task(TaskCreate(project_id=project.id, title="T"))
    await svc.update_status(task.id, "ongoing", actor="agent")
    await svc.update_status(task.id, "completed", actor="agent")
    fetched = await svc.get_task(task.id)
    assert fetched.status == "completed"
    assert fetched.started_at is not None
    assert fetched.completed_at is not None


@pytest.mark.asyncio
async def test_status_state_machine_invalid_transition(session):
    project = await _project(session)
    svc = TaskService(session)
    task = await svc.create_task(TaskCreate(project_id=project.id, title="T"))
    # not_started -> completed is NOT allowed (must go through ongoing).
    with pytest.raises(ValueError):
        await svc.update_status(task.id, "completed", actor="agent")
    # Move to rejected (allowed), then rejected -> ongoing is NOT allowed.
    await svc.update_status(task.id, "rejected", actor="agent")
    with pytest.raises(ValueError):
        await svc.update_status(task.id, "ongoing", actor="agent")


@pytest.mark.asyncio
async def test_dequeue_respects_priority(session):
    project = await _project(session)
    svc = TaskService(session)
    low = await svc.create_task(
        TaskCreate(project_id=project.id, title="low", priority=1)
    )
    high = await svc.create_task(
        TaskCreate(project_id=project.id, title="high", priority=10)
    )
    nxt = await svc.get_next_task(project.id)
    assert nxt is not None
    assert nxt.id == high.id


@pytest.mark.asyncio
async def test_dequeue_respects_dependencies(session):
    project = await _project(session)
    svc = TaskService(session)
    # Blocker is "ongoing" (in progress, not dequeueable itself).
    blocker = await svc.create_task(TaskCreate(project_id=project.id, title="blocker"))
    await svc.update_status(blocker.id, "ongoing")
    waiting = await svc.create_task(
        TaskCreate(
            project_id=project.id, title="waiting", depends_on=[blocker.id]
        )
    )
    # waiting is blocked by the still-incomplete blocker -> nothing to dequeue.
    assert await svc.check_dependencies(waiting.id) is False
    assert await svc.get_next_task(project.id) is None
    # complete the blocker -> waiting becomes ready and is dequeued.
    await svc.update_status(blocker.id, "completed")
    assert await svc.check_dependencies(waiting.id) is True
    nxt = await svc.get_next_task(project.id)
    assert nxt is not None
    assert nxt.id == waiting.id


@pytest.mark.asyncio
async def test_get_ready_tasks(session):
    project = await _project(session)
    svc = TaskService(session)
    a = await svc.create_task(TaskCreate(project_id=project.id, title="a"))
    b = await svc.create_task(
        TaskCreate(project_id=project.id, title="b", depends_on=[a.id])
    )
    ready = await svc.get_ready_tasks(project.id)
    assert [t.id for t in ready] == [a.id]
    await svc.update_status(a.id, "ongoing")
    await svc.update_status(a.id, "completed")
    ready = await svc.get_ready_tasks(project.id)
    assert [t.id for t in ready] == [b.id]


@pytest.mark.asyncio
async def test_add_message_appends_to_log(session):
    project = await _project(session)
    svc = TaskService(session)
    task = await svc.create_task(TaskCreate(project_id=project.id, title="T"))
    await svc.add_message(task.id, "agent", "starting work", "progress")
    msgs = await svc.list_messages(task.id)
    assert len(msgs) == 1
    assert msgs[0].content == "starting work"
