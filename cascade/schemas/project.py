"""Project request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    mission: Optional[str] = None


class ProjectCreate(ProjectBase):
    status: str = Field("active", pattern="^(active|archived|completed)$")


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    mission: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|archived|completed)$")


class ProjectResponse(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    created_at: datetime
    updated_at: datetime
