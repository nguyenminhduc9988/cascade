"""Message schemas for the append-only conversation log."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    task_id: str
    author: str = Field("agent", pattern="^(human|agent|system)$")
    content: str = Field(..., min_length=1)
    message_type: str = Field(
        "reply",
        pattern="^(reply|progress|permission_request|permission_response|system|error)$",
    )
    metadata_json: Optional[str] = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    author: str
    content: str
    message_type: str
    metadata_json: Optional[str] = None
    created_at: datetime
