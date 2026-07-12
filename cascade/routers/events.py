"""Event REST endpoints — /api/events (publish + triggers)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.database import get_db
from cascade.schemas import (
    EventCreate,
    EventResponse,
    EventTriggerCreate,
    EventTriggerResponse,
)
from cascade.schemas.event import EventPublish
from cascade.services.event_service import EventService

router = APIRouter(prefix="/api/events", tags=["events"])


def _service(session: AsyncSession = Depends(get_db)) -> EventService:
    return EventService(session)


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(data: EventCreate, svc: EventService = Depends(_service)):
    """Define a named event for cross-project choreography."""
    return await svc.create_event(data)


@router.get("", response_model=list[EventResponse])
async def list_events(project_id: str, svc: EventService = Depends(_service)):
    """List events defined for a project."""
    return await svc.list_events(project_id)


@router.post("/publish")
async def publish_event(data: EventPublish, svc: EventService = Depends(_service)):
    """Publish a live event occurrence (fires any matching triggers)."""
    try:
        return await svc.publish_event(data)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/triggers",
    response_model=EventTriggerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_trigger(
    data: EventTriggerCreate, svc: EventService = Depends(_service)
):
    """Register a trigger that materialises a task when an event fires."""
    return await svc.create_trigger(data)


@router.get("/triggers", response_model=list[EventTriggerResponse])
async def list_triggers(project_id: str, svc: EventService = Depends(_service)):
    """List triggers for a project."""
    return await svc.list_triggers(project_id)
