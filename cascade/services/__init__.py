"""Business-logic services.

Services are thin, stateless functions that take an :class:`AsyncSession` and
delegate persistence to SQLAlchemy models. Routers stay thin and delegate here.
"""

from cascade.services.auto_decision import AutoDecisionService
from cascade.services.event_service import EventService
from cascade.services.goal_service import GoalService
from cascade.services.milestone_service import MilestoneService
from cascade.services.monitor_service import MonitorService
from cascade.services.project_service import ProjectService
from cascade.services.scheduler_service import SchedulerService
from cascade.services.task_service import TaskService

__all__ = [
    "AutoDecisionService",
    "EventService",
    "GoalService",
    "MilestoneService",
    "MonitorService",
    "ProjectService",
    "SchedulerService",
    "TaskService",
]
