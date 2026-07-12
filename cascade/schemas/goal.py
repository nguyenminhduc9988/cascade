"""Goal request/response schemas, including computed progress."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GoalBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    metric_name: Optional[str] = None
    target_value: float = 100.0
    auto_aggregate: bool = True
    sort_order: int = 0


class GoalCreate(GoalBase):
    project_id: str
    status: str = Field("active", pattern="^(active|achieved|abandoned)$")


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    metric_name: Optional[str] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    auto_aggregate: Optional[bool] = None
    status: Optional[str] = Field(None, pattern="^(active|achieved|abandoned)$")
    sort_order: Optional[int] = None


class GoalResponse(GoalBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    current_value: float
    status: str
    created_at: datetime


class GoalProgress(BaseModel):
    """Read-time computed progress for a single goal."""

    id: str
    title: str
    metric_name: Optional[str] = None
    target_value: float
    current_value: float
    percentage: float
    task_total: int
    task_completed: int
    status: str
