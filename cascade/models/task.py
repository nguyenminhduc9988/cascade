"""Task — the unified work item (the CORE model).

A single polymorphic model (like Leantime's ``zp_tickets``) that supports:
* a status state machine (from AgentRQ)
* bidirectional human/agent delegation
* self-referential hierarchy (parent/children)
* explicit goal + milestone links (strategic coherence)
* cron-template spawning (from AgentRQ)
* event choreography via ``emit_event_id``
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cascade.database import Base

if TYPE_CHECKING:
    from cascade.models.dependency import TaskDependency
    from cascade.models.event import Event
    from cascade.models.goal import Goal
    from cascade.models.message import Message
    from cascade.models.milestone import Milestone
    from cascade.models.project import Project


class Task(Base):
    """Unified work item with a status state machine and DAG dependencies."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Type discriminator (single polymorphic model)
    type: Mapped[str] = mapped_column(String(20), default="task")  # epic|story|task|subtask

    # Status state machine (from AgentRQ)
    status: Mapped[str] = mapped_column(
        String(20), default="not_started", index=True
    )  # not_started|ongoing|completed|blocked|rejected|cron

    # Assignment (bidirectional delegation from AgentRQ)
    created_by: Mapped[str] = mapped_column(String(20), default="human")  # human|agent|system
    assignee: Mapped[str] = mapped_column(String(20), default="agent")  # human|agent

    # Hierarchy (self-referential parent)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), index=True)

    # Strategic links (IMPROVEMENT over Leantime's informal connection)
    goal_id: Mapped[Optional[str]] = mapped_column(ForeignKey("goals.id"), index=True)
    milestone_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("milestones.id"), index=True
    )

    # Effort metadata
    priority: Mapped[int] = mapped_column(Integer, default=0)  # higher = more important
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    story_points: Mapped[Optional[int]] = mapped_column(Integer)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float)

    # Cron template support (from AgentRQ)
    cron_schedule: Mapped[Optional[str]] = mapped_column(String(100))
    cron_template_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("tasks.id")
    )  # parent template

    # Event choreography (from AgentRQ)
    emit_event_id: Mapped[Optional[str]] = mapped_column(ForeignKey("events.id"))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Composite index for dequeue query (from AgentRQ's idx_tasks_dequeue)
    __table_args__ = (
        Index("idx_tasks_dequeue", "project_id", "assignee", "status"),
    )

    # --- Relationships ---
    project: Mapped["Project"] = relationship(back_populates="tasks")
    goal: Mapped[Optional["Goal"]] = relationship(back_populates="tasks")
    milestone: Mapped[Optional["Milestone"]] = relationship(back_populates="tasks")

    parent: Mapped[Optional["Task"]] = relationship(
        "Task",
        remote_side="Task.id",
        back_populates="children",
        foreign_keys=[parent_id],
    )
    children: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="parent",
        foreign_keys=[parent_id],
    )

    cron_template: Mapped[Optional["Task"]] = relationship(
        "Task",
        remote_side="Task.id",
        foreign_keys=[cron_template_id],
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    dependencies_as_dep: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.depends_on_id",
        back_populates="depends_on_task",
        cascade="all, delete-orphan",
    )
    dependencies_as_blocked: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.task_id",
        back_populates="task",
        cascade="all, delete-orphan",
    )

    emit_event: Mapped[Optional["Event"]] = relationship("Event")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Task {self.id} {self.title!r} [{self.status}]>"
