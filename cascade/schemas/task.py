"""Task request/response schemas, including status transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from cascade.schemas.message import MessageResponse

# Valid task statuses (state machine states).
TASK_STATUSES = {
    "not_started",
    "ongoing",
    "completed",
    "blocked",
    "rejected",
    "cron",
}

TASK_TYPES = {"epic", "story", "task", "subtask"}


class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    type: str = Field("task", pattern="^(epic|story|task|subtask)$")


class TaskCreate(TaskBase):
    project_id: Optional[str] = None  # may be inferred from parent
    status: str = Field("not_started", pattern="^(not_started|ongoing|cron)$")
    created_by: str = Field("human", pattern="^(human|agent)$")
    assignee: str = Field("agent", pattern="^(human|agent)$")
    parent_id: Optional[str] = None
    goal_id: Optional[str] = None
    milestone_id: Optional[str] = None
    priority: int = 0
    sort_order: int = 0
    story_points: Optional[int] = None
    estimated_hours: Optional[float] = None
    cron_schedule: Optional[str] = None
    emit_event_id: Optional[str] = None
    depends_on: Optional[list[str]] = None  # list of task IDs to depend on


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(epic|story|task|subtask)$")
    assignee: Optional[str] = Field(None, pattern="^(human|agent)$")
    parent_id: Optional[str] = None
    goal_id: Optional[str] = None
    milestone_id: Optional[str] = None
    priority: Optional[int] = None
    sort_order: Optional[int] = None
    story_points: Optional[int] = None
    estimated_hours: Optional[float] = None


class TaskStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(not_started|ongoing|completed|blocked|rejected|cron)$")
    reason: Optional[str] = None


class TaskResponse(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    created_by: str
    assignee: str
    parent_id: Optional[str] = None
    goal_id: Optional[str] = None
    milestone_id: Optional[str] = None
    priority: int
    sort_order: int
    story_points: Optional[int] = None
    estimated_hours: Optional[float] = None
    cron_schedule: Optional[str] = None
    cron_template_id: Optional[str] = None
    emit_event_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    dependencies_ready: bool = False
    depends_on: list[str] = []
    blocks: list[str] = []
    messages: list[MessageResponse] = []
