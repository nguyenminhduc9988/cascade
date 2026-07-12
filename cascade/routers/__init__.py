"""FastAPI routers (thin handlers that delegate to services)."""

from cascade.routers import (
    dashboard,
    events,
    goals,
    milestones,
    pages,
    projects,
    tasks,
)

__all__ = [
    "dashboard",
    "events",
    "goals",
    "milestones",
    "pages",
    "projects",
    "tasks",
]
