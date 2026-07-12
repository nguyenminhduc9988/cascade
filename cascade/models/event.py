"""Event + EventTrigger — cross-workspace choreography from AgentRQ."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from cascade.database import Base


class Event(Base):
    """A named, publishable event scoped to a project.

    Tasks can declare ``emit_event_id`` to publish this event on completion,
    enabling cross-project choreography through matching triggers.
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)  # event name/key
    description: Mapped[Optional[str]] = mapped_column(Text)
    payload_json: Mapped[Optional[str]] = mapped_column(Text)  # template payload
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Event {self.id} {self.name!r}>"


class EventTrigger(Base):
    """A listener that auto-creates a task from a template when an event fires.

    When an event matching ``event_name`` is published, the
    ``task_template_json`` is used to materialise a new task — wiring up
    cross-project automation.
    """

    __tablename__ = "event_triggers"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    event_name: Mapped[str] = mapped_column(String(100), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    task_template_json: Mapped[str] = mapped_column(Text)  # JSON template
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<EventTrigger {self.id} on {self.event_name!r}>"
