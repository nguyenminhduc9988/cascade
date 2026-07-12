"""Monitor service — agent liveness, stall detection and progress tracking.

THE KEY IMPROVEMENT over AgentRQ: a live in-memory registry of agent sessions
per project, used to drive the dashboard's "agent alive" indicator, detect
stalled tasks and broadcast real-time progress over SSE.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cascade.config import settings
from cascade.engine.progress_tracker import tracker
from cascade.models import Message, Task, Telemetry
from cascade.services.task_service import TaskService

logger = logging.getLogger(__name__)


class MonitorService:
    """Agent liveness + stall detection + completion verification."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # project_id -> {session_id: last_seen_datetime}
        # Shared at module level so it survives across request-scoped sessions.
        self._sessions = _AGENT_SESSIONS

    # ----------------------------------------------------- SESSION LIVENESS
    async def register_agent_session(
        self, project_id: str, session_id: str
    ) -> None:
        """Register (or refresh) a live agent connection for a project."""
        self._sessions.setdefault(project_id, {})[session_id] = datetime.now(
            timezone.utc
        )

    async def heartbeat(self, project_id: str, session_id: str) -> None:
        """Update the last-seen timestamp for a session."""
        await self.register_agent_session(project_id, session_id)

    async def evict_dead_sessions(self, timeout_seconds: int | None = None) -> int:
        """Remove sessions older than the timeout; return the count evicted."""
        timeout = timeout_seconds or settings.session_timeout_seconds
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout)
        evicted = 0
        for project_id, sessions in list(self._sessions.items()):
            dead = [sid for sid, seen in sessions.items() if seen < cutoff]
            for sid in dead:
                sessions.pop(sid, None)
                evicted += 1
            if not sessions:
                self._sessions.pop(project_id, None)
        return evicted

    async def is_agent_alive(self, project_id: str) -> bool:
        """Return True if at least one non-stale agent session exists."""
        sessions = self._sessions.get(project_id, {})
        if not sessions:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=settings.session_timeout_seconds
        )
        return any(seen >= cutoff for seen in sessions.values())

    async def live_projects(self) -> dict[str, int]:
        """Return {project_id: live_session_count} for the dashboard."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=settings.session_timeout_seconds
        )
        return {
            pid: sum(1 for seen in sessions.values() if seen >= cutoff)
            for pid, sessions in self._sessions.items()
            if any(seen >= cutoff for seen in sessions.values())
        }

    # ------------------------------------------------------- STALL DETECTION
    async def get_stalled_tasks(
        self, project_id: str, threshold_minutes: int | None = None
    ) -> list[Task]:
        """Return ``ongoing`` tasks with no message within the threshold."""
        threshold = threshold_minutes or settings.stall_threshold_minutes
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=threshold)

        tasks = await self.session.execute(
            select(Task).where(
                Task.project_id == project_id, Task.status == "ongoing"
            )
        )
        stalled: list[Task] = []
        for task in tasks.scalars().all():
            last_msg = await self.session.execute(
                select(func.max(Message.created_at)).where(
                    Message.task_id == task.id
                )
            )
            last = last_msg.scalar_one_or_none()
            # Stalled if no message at all, or last message older than cutoff.
            if last is None or _to_utc(last) < cutoff:
                stalled.append(task)
        return stalled

    async def nudge_stalled_task(self, task_id: str) -> Message | None:
        """Send a status-check message to a stalled task."""
        task = await self.session.get(Task, task_id)
        if task is None:
            return None
        task_service = TaskService(self.session)
        return await task_service.add_message(
            task_id=task_id,
            author="system",
            content=(
                "Stall check: this task has been ongoing without updates. "
                "Please report progress or update status."
            ),
            message_type="system",
            metadata={"nudge": True, "task_id": task_id},
        )

    # ------------------------------------------------------- BROADCASTING
    async def broadcast_progress(
        self, project_id: str, task_id: str, content: str
    ) -> None:
        """Broadcast a progress update to all SSE subscribers of a project."""
        await tracker.publish(
            project_id,
            "progress",
            {"task_id": task_id, "content": content},
        )

    # --------------------------------------------------- COMPLETION CHECK
    async def check_completion(self, task_id: str) -> bool:
        """Heuristically verify whether a task is truly done.

        Considers the task "done" if its status is ``completed`` *or* the most
        recent non-system message looks like a completion/summary report.
        """
        task = await self.session.get(Task, task_id)
        if task is None:
            return False
        if task.status == "completed":
            return True

        last = await self.session.execute(
            select(Message)
            .where(Message.task_id == task_id)
            # ULID ids are monotonic, so they break sub-second timestamp ties.
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(1)
        )
        msg = last.scalars().first()
        if msg is None:
            return False
        content = (msg.content or "").lower()
        completion_markers = ("completed", "done", "finished", "summary")
        return any(marker in content for marker in completion_markers)

    # --------------------------------------------------- ACTIVITY FEED
    async def recent_activity(
        self, project_id: str | None = None, limit: int = 20
    ) -> list[Telemetry]:
        """Return recent telemetry entries for the dashboard feed."""
        stmt = select(Telemetry).order_by(desc(Telemetry.created_at)).limit(limit)
        if project_id:
            stmt = stmt.where(Telemetry.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# Module-level registry shared across all MonitorService instances.
_AGENT_SESSIONS: dict[str, dict[str, datetime]] = {}


def _to_utc(value: datetime) -> datetime:
    """Normalise a naive/aware datetime to aware UTC for comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
