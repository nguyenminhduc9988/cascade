"""Goal — strategic, measurable objective with progress aggregation."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cascade.database import Base

if TYPE_CHECKING:
    from cascade.models.project import Project
    from cascade.models.task import Task


class Goal(Base):
    """A measurable strategic goal.

    When ``auto_aggregate`` is True, :attr:`current_value` is derived at
    read-time from the progress of linked tasks (completed/total). Otherwise it
    is a manual counter. Progress is *never* denormalised — always computed.
    """

    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

    metric_name: Mapped[Optional[str]] = mapped_column(String(100))  # e.g. "tasks completed"
    target_value: Mapped[float] = mapped_column(default=100.0)
    current_value: Mapped[float] = mapped_column(default=0.0)
    auto_aggregate: Mapped[bool] = mapped_column(default=True)

    status: Mapped[str] = mapped_column(String(20), default="active")  # active|achieved|abandoned
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="goals")
    tasks: Mapped[list["Task"]] = relationship(back_populates="goal")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Goal {self.id} {self.title!r}>"
