"""Tests for ProjectService — cascade deletion across all linked entities."""

from __future__ import annotations

import pytest

from cascade.schemas.event import EventCreate, EventTriggerCreate
from cascade.schemas.project import ProjectCreate
from cascade.schemas.task import TaskCreate
from cascade.services.event_service import EventService
from cascade.services.project_service import ProjectService
from cascade.services.task_service import TaskService


@pytest.mark.asyncio
async def test_delete_project_cascades_events_and_triggers(session):
    """Deleting a project must not leave orphaned Event/EventTrigger rows
    (this matters once PRAGMA foreign_keys=ON is enforced in production)."""
    project_svc = ProjectService(session)
    event_svc = EventService(session)

    project = await project_svc.create_project(ProjectCreate(name="Doomed"))
    await event_svc.create_event(EventCreate(project_id=project.id, name="deploy_done"))
    await event_svc.create_trigger(
        EventTriggerCreate(
            event_name="deploy_done",
            project_id=project.id,
            task_template={"title": "x", "project_id": project.id},
        )
    )

    assert await project_svc.delete_project(project.id) is True

    assert await event_svc.list_events(project.id) == []
    assert await event_svc.list_triggers(project.id) == []


@pytest.mark.asyncio
async def test_delete_project_with_parent_child_tasks_does_not_violate_fk(session):
    """Cascade-deleting a project's tasks must not trip the self-referential
    parent_id/cron_template_id foreign key under PRAGMA foreign_keys=ON."""
    project_svc = ProjectService(session)
    task_svc = TaskService(session)

    project = await project_svc.create_project(ProjectCreate(name="Doomed"))
    parent = await task_svc.create_task(TaskCreate(project_id=project.id, title="epic"))
    await task_svc.create_task(
        TaskCreate(project_id=project.id, title="subtask", parent_id=parent.id)
    )

    assert await project_svc.delete_project(project.id) is True
