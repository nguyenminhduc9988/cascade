"""SQLAlchemy 2.0 typed models for Cascade.

Importing this package registers every model on :class:`cascade.database.Base`
so that ``Base.metadata`` is fully populated before table creation/migrations.
"""

from cascade.models.dependency import TaskDependency
from cascade.models.event import Event, EventTrigger
from cascade.models.goal import Goal
from cascade.models.message import Message
from cascade.models.milestone import Milestone
from cascade.models.project import Project
from cascade.models.task import Task
from cascade.models.telemetry import Telemetry

__all__ = [
    "Event",
    "EventTrigger",
    "Goal",
    "Message",
    "Milestone",
    "Project",
    "Task",
    "TaskDependency",
    "Telemetry",
]
