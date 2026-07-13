"""Project — the strategic coherence anchor for a workspace."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cascade.database import Base

if TYPE_CHECKING:
    from cascade.models.event import Event, EventTrigger
    from cascade.models.goal import Goal
    from cascade.models.milestone import Milestone
    from cascade.models.task import Task


class Project(Base):
    """Top-level workspace that groups goals, milestones and tasks.

    The ``mission`` field carries the high-level objective brief that agents
    read via ``get_mission`` to maintain strategic coherence.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|archived|completed
    mission: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    goals: Mapped[list["Goal"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    event_triggers: Mapped[list["EventTrigger"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Project {self.id} {self.name!r}>"
