"""Tests for TaskService — state machine, dequeue and DAG resolution."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.dml import Update

from cascade.models import Project, Task
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
    _low = await svc.create_task(
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


@pytest.mark.asyncio
async def test_add_message_rejects_nonexistent_task(session):
    svc = TaskService(session)
    with pytest.raises(ValueError):
        await svc.add_message("does-not-exist", "agent", "hi", "progress")


@pytest.mark.asyncio
async def test_dequeue_claims_the_task(session):
    """Dequeue must atomically claim the task (not_started -> ongoing)."""
    project = await _project(session)
    svc = TaskService(session)
    task = await svc.create_task(TaskCreate(project_id=project.id, title="T"))
    claimed = await svc.get_next_task(project.id)
    assert claimed is not None
    assert claimed.id == task.id
    assert claimed.status == "ongoing"
    assert claimed.started_at is not None
    # Already claimed -> a second dequeue must not return it again.
    assert await svc.get_next_task(project.id) is None


@pytest.mark.asyncio
async def test_concurrent_dequeue_never_double_claims(engine):
    """Two agents racing to dequeue the same task must not both win it."""
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as setup_session:
        project = await _project(setup_session)
        setup_svc = TaskService(setup_session)
        task = await setup_svc.create_task(
            TaskCreate(project_id=project.id, title="contested")
        )

    async def _dequeue():
        async with factory() as session:
            return await TaskService(session).get_next_task(project.id)

    results = await asyncio.gather(_dequeue(), _dequeue())
    winners = [r for r in results if r is not None and r.id == task.id]
    assert len(winners) == 1


@pytest.mark.asyncio
async def test_update_status_rejects_concurrent_status_change(session):
    """If the row's status changes between update_status's read and its
    atomic conditional write, the write must be rejected — not silently
    applied on top of a state the caller never validated against."""
    project = await _project(session)
    svc = TaskService(session)
    task = await svc.create_task(TaskCreate(project_id=project.id, title="race"))
    await svc.update_status(task.id, "ongoing")

    original_execute = svc.session.execute
    raced = False

    async def _execute_with_race_before_the_atomic_update(stmt, *args, **kwargs):
        nonlocal raced
        if not raced and isinstance(stmt, Update):
            raced = True
            # Simulate another writer completing the task in the gap between
            # update_status's validation read and its own atomic write below.
            await original_execute(
                update(Task).where(Task.id == task.id).values(status="completed")
            )
            await svc.session.commit()
        return await original_execute(stmt, *args, **kwargs)

    svc.session.execute = _execute_with_race_before_the_atomic_update
    with pytest.raises(ValueError, match="concurrently"):
        await svc.update_status(task.id, "blocked")

    # The racing writer's change must have stuck — the loser never overwrote it.
    svc.session.execute = original_execute
    refetched = await svc.get_task(task.id)
    assert refetched.status == "completed"


@pytest.mark.asyncio
async def test_create_task_rejects_unknown_dependency(session):
    project = await _project(session)
    svc = TaskService(session)
    with pytest.raises(ValueError):
        await svc.create_task(
            TaskCreate(project_id=project.id, title="T", depends_on=["does-not-exist"])
        )


@pytest.mark.asyncio
async def test_delete_task_unlinks_children_instead_of_orphaning(session):
    project = await _project(session)
    svc = TaskService(session)
    parent = await svc.create_task(TaskCreate(project_id=project.id, title="epic"))
    child = await svc.create_task(
        TaskCreate(project_id=project.id, title="subtask", parent_id=parent.id)
    )

    assert await svc.delete_task(parent.id) is True

    refetched = await svc.get_task(child.id)
    assert refetched is not None
    assert refetched.parent_id is None
