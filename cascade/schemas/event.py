"""Event + EventTrigger schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


class EventPublish(BaseModel):
    """Publish a live event occurrence (may fire triggers)."""

    project_id: str
    name: str
    payload: Optional[dict[str, Any]] = None


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    payload_json: Optional[str] = None
    created_at: datetime


class EventTriggerCreate(BaseModel):
    event_name: str
    project_id: str
    task_template: dict[str, Any]


class EventTriggerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_name: str
    project_id: str
    task_template_json: str
    created_at: datetime
