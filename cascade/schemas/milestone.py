"""Milestone request/response schemas with progress rollup."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class MilestoneBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    sort_order: int = 0


class MilestoneCreate(MilestoneBase):
    project_id: str
    status: str = Field("planned", pattern="^(planned|active|completed)$")


class MilestoneUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = Field(None, pattern="^(planned|active|completed)$")
    sort_order: Optional[int] = None


class MilestoneResponse(MilestoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    created_at: datetime
    task_total: int = 0
    task_completed: int = 0
    progress_percentage: float = 0.0
