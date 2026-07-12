"""Event service — event publishing + trigger matching for choreography."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.engine.progress_tracker import tracker
from cascade.models import Event, EventTrigger
from cascade.schemas import (
    EventCreate,
    EventPublish,
    EventTriggerCreate,
)
from cascade.services.task_service import TaskService
from cascade.schemas.task import TaskCreate
from cascade.utils import dumps, new_id

logger = logging.getLogger(__name__)


class EventService:
    """Event definition, publishing and trigger-driven task creation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_event(self, data: EventCreate) -> Event:
        """Define a named event (a reusable choreography signal)."""
        event = Event(
            id=new_id(),
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            payload_json=dumps(data.payload) if data.payload else None,
        )
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def list_events(self, project_id: str) -> list[Event]:
        """List events defined for a project."""
        result = await self.session.execute(
            select(Event).where(Event.project_id == project_id)
        )
        return list(result.scalars().all())

    async def create_trigger(self, data: EventTriggerCreate) -> EventTrigger:
        """Register a trigger that materialises a task from a template."""
        trigger = EventTrigger(
            id=new_id(),
            event_name=data.event_name,
            project_id=data.project_id,
            task_template_json=dumps(data.task_template),
        )
        self.session.add(trigger)
        await self.session.commit()
        await self.session.refresh(trigger)
        return trigger

    async def list_triggers(self, project_id: str) -> list[EventTrigger]:
        """List triggers for a project."""
        result = await self.session.execute(
            select(EventTrigger).where(EventTrigger.project_id == project_id)
        )
        return list(result.scalars().all())

    async def publish_event(self, data: EventPublish) -> dict:
        """Publish a live event occurrence and fire any matching triggers.

        Each matching trigger materialises a ``not_started`` task from its
        template, wiring up cross-project automation.
        """
        await tracker.publish(
            data.project_id,
            f"event:{data.name}",
            {"name": data.name, "payload": data.payload or {}},
        )

        triggers = await self.session.execute(
            select(EventTrigger).where(EventTrigger.event_name == data.name)
        )
        task_service = TaskService(self.session)
        created: list[str] = []
        for trigger in triggers.scalars().all():
            from cascade.utils import loads

            template = loads(trigger.task_template_json)
            template.setdefault("project_id", trigger.project_id)
            template["created_by"] = "system"
            try:
                task = await task_service.create_task(TaskCreate(**template))
                created.append(task.id)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to materialise trigger task")

        return {
            "event": data.name,
            "project_id": data.project_id,
            "tasks_created": created,
        }
