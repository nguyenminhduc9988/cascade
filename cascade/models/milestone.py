"""Milestone — a time-boxed grouping of tasks."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cascade.database import Base

if TYPE_CHECKING:
    from cascade.models.project import Project
    from cascade.models.task import Task


class Milestone(Base):
    """A time-boxed container that groups related tasks together.

    Supports a progress rollup (completed tasks / total tasks) displayed on the
    project timeline view.
    """

    __tablename__ = "milestones"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|active|completed
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="milestones")
    tasks: Mapped[list["Task"]] = relationship(back_populates="milestone")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Milestone {self.id} {self.title!r}>"
