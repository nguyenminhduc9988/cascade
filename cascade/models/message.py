"""Message — append-only conversation log per task."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cascade.database import Base

if TYPE_CHECKING:
    from cascade.models.task import Task


class Message(Base):
    """An immutable log entry attached to a task.

    ``message_type`` discriminates how the message should be rendered/acted on:
    ``reply``, ``progress``, ``permission_request``, ``permission_response``,
    ``system`` or ``error``. ``metadata_json`` carries type-specific payloads.
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    author: Mapped[str] = mapped_column(String(20))  # human|agent|system
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(30), default="reply")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    task: Mapped["Task"] = relationship(back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Message {self.id} [{self.message_type}]>"
