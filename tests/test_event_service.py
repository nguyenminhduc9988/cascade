"""Tests for EventService — trigger materialisation and completion choreography."""

from __future__ import annotations

import pytest

from cascade.models import Event, Project
from cascade.schemas.event import EventTriggerCreate
from cascade.schemas.task import TaskCreate
from cascade.services.event_service import EventService
from cascade.services.task_service import TaskService


async def _project(session) -> Project:
    project = Project(id="01PROJECT0000000000000000004", name="Events")
    session.add(project)
    await session.commit()
    return project


@pytest.mark.asyncio
async def test_publish_event_materialises_trigger_task(session):
    project = await _project(session)
    event_svc = EventService(session)

    await event_svc.create_trigger(
        EventTriggerCreate(
            event_name="deploy_done",
            project_id=project.id,
            task_template={"title": "Notify stakeholders", "project_id": project.id},
        )
    )

    from cascade.schemas.event import EventPublish

    result = await event_svc.publish_event(
        EventPublish(project_id=project.id, name="deploy_done")
    )
    assert len(result["tasks_created"]) == 1

    task_svc = TaskService(session)
    tasks = await task_svc.get_tasks_by_project(project.id)
    assert any(t.title == "Notify stakeholders" and t.created_by == "system" for t in tasks)


@pytest.mark.asyncio
async def test_task_completion_fires_declared_event(session):
    project = await _project(session)
    event = Event(id="01EVENT00000000000000000001", project_id=project.id, name="deploy_done")
    session.add(event)
    await session.commit()

    event_svc = EventService(session)
    await event_svc.create_trigger(
        EventTriggerCreate(
            event_name="deploy_done",
            project_id=project.id,
            task_template={"title": "Notify stakeholders", "project_id": project.id},
        )
    )

    task_svc = TaskService(session)
    task = await task_svc.create_task(
        TaskCreate(project_id=project.id, title="Deploy", emit_event_id=event.id)
    )
    await task_svc.update_status(task.id, "ongoing")
    await task_svc.update_status(task.id, "completed")

    tasks = await task_svc.get_tasks_by_project(project.id)
    assert any(t.title == "Notify stakeholders" for t in tasks)
