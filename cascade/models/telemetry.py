"""Telemetry — immutable audit trail of every meaningful action."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from cascade.database import Base


class Telemetry(Base):
    """A single audit record capturing *who* did *what* and the details.

    Used to populate the dashboard's recent-activity feed and provide a full
    history of tool calls, status changes and permission decisions.
    """

    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[Optional[str]] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), index=True)
    action: Mapped[str] = mapped_column(
        String(100)
    )  # tool_call|status_change|permission|...
    actor: Mapped[str] = mapped_column(String(50))  # human|agent|system
    details_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Telemetry {self.id} {self.action!r} by {self.actor}>"
