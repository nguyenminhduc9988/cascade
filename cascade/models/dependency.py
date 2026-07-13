"""TaskDependency — DAG edges between tasks.

An improvement over Leantime's single ``dependingTicketId`` parent pointer:
this models a full directed acyclic graph where ``task_id`` is blocked until
``depends_on_id`` is completed.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cascade.database import Base

if TYPE_CHECKING:
    from cascade.models.task import Task


class TaskDependency(Base):
    """A single dependency edge: ``task_id`` depends on ``depends_on_id``."""

    __tablename__ = "task_dependencies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id"), index=True
    )  # the task that is blocked
    depends_on_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id"), index=True
    )  # the task it waits for
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    task: Mapped["Task"] = relationship(
        "Task", foreign_keys=[task_id], back_populates="dependencies_as_blocked"
    )
    depends_on_task: Mapped["Task"] = relationship(
        "Task", foreign_keys=[depends_on_id], back_populates="dependencies_as_dep"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TaskDependency {self.task_id} depends_on {self.depends_on_id}>"
