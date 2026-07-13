"""Task service — CRUD, dequeue, status state machine and DAG resolution.

The heart of AgentRQ's pull-based work queue, reimagined in Python:
* :meth:`get_next_task` dequeues the highest-priority ready task.
* :meth:`update_status` enforces the state machine.
* :meth:`check_dependencies` / :meth:`get_ready_tasks` resolve the DAG.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cascade.engine.progress_tracker import tracker
from cascade.models import Message, Task, TaskDependency, Telemetry
from cascade.schemas import TaskCreate, TaskUpdate
from cascade.utils import dumps, new_id

logger = logging.getLogger(__name__)

# Allowed state-machine transitions (per the Cascade spec).
# not_started -> ongoing -> completed|blocked|rejected ; blocked -> ongoing ; cron spawns.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "not_started": {"ongoing", "blocked", "rejected", "cron"},
    "ongoing": {"completed", "blocked", "rejected"},
    "blocked": {"ongoing", "rejected", "completed"},
    "completed": {"ongoing", "not_started"},  # allow reopen
    "rejected": {"not_started"},  # allow re-queue
    "cron": {"ongoing", "not_started", "blocked"},
}


class TaskService:
    """CRUD + dequeue + state machine + DAG resolution for tasks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ CRUD
    async def create_task(self, data: TaskCreate) -> Task:
        """Create a task with an auto ULID and optional dependencies."""
        project_id = data.project_id
        if project_id is None and data.parent_id:
            parent = await self.get_task(data.parent_id)
            project_id = parent.project_id if parent else None
        if project_id is None:
            raise ValueError("project_id is required (or a valid parent_id)")

        task = Task(
            id=new_id(),
            project_id=project_id,
            title=data.title,
            description=data.description,
            type=data.type,
            status=data.status,
            created_by=data.created_by,
            assignee=data.assignee,
            parent_id=data.parent_id,
            goal_id=data.goal_id,
            milestone_id=data.milestone_id,
            priority=data.priority,
            sort_order=data.sort_order,
            story_points=data.story_points,
            estimated_hours=data.estimated_hours,
            cron_schedule=data.cron_schedule,
            emit_event_id=data.emit_event_id,
        )
        if data.status == "ongoing":
            task.started_at = datetime.now(timezone.utc)

        self.session.add(task)
        await self.session.flush()

        # Wire up DAG dependencies.
        for dep_id in data.depends_on or []:
            if dep_id == task.id:
                continue
            self.session.add(
                TaskDependency(task_id=task.id, depends_on_id=dep_id)
            )

        await self._record_telemetry(
            project_id=task.project_id,
            task_id=task.id,
            action="task_created",
            actor=task.created_by,
            details={"title": task.title, "type": task.type},
        )
        await self.session.commit()
        await self.session.refresh(task)

        await tracker.publish(
            task.project_id,
            "task_created",
            {"task_id": task.id, "title": task.title, "status": task.status},
        )
        return task

    async def get_task(self, task_id: str) -> Task | None:
        """Fetch a task with messages, dependencies and children eagerly loaded."""
        result = await self.session.execute(
            select(Task)
            .options(
                selectinload(Task.messages),
                selectinload(Task.dependencies_as_blocked).selectinload(
                    TaskDependency.depends_on_task
                ),
                selectinload(Task.dependencies_as_dep).selectinload(
                    TaskDependency.task
                ),
                selectinload(Task.children),
            )
            .where(Task.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_tasks_by_project(
        self,
        project_id: str,
        status: str | None = None,
        goal_id: str | None = None,
        milestone_id: str | None = None,
        parent_id: str | None = None,
    ) -> list[Task]:
        """Return filtered tasks for a project."""
        stmt = select(Task).where(Task.project_id == project_id)
        if status:
            stmt = stmt.where(Task.status == status)
        if goal_id:
            stmt = stmt.where(Task.goal_id == goal_id)
        if milestone_id:
            stmt = stmt.where(Task.milestone_id == milestone_id)
        if parent_id is not None:
            if parent_id == "":
                stmt = stmt.where(Task.parent_id.is_(None))
            else:
                stmt = stmt.where(Task.parent_id == parent_id)
        stmt = stmt.order_by(Task.priority.desc(), Task.sort_order, Task.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_task(self, task_id: str, data: TaskUpdate) -> Task | None:
        """Partially update a task (does not touch status — use update_status)."""
        task = await self.get_task(task_id)
        if task is None:
            return None
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(task, key, value)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task and its cascade-orphaned messages/dependencies.

        Any subtasks or cron-spawned children pointing at this task are
        unlinked first (``parent_id``/``cron_template_id`` -> ``NULL``), as
        is the immutable :class:`~cascade.models.telemetry.Telemetry` audit
        trail (which is never deleted, only unlinked) — so deleting a task
        never leaves a dangling foreign key behind. These are ORM-managed
        attribute mutations (not a raw bulk ``UPDATE``) so the unit of work
        orders the NULL-out UPDATEs before the DELETE at flush time —
        required now that ``PRAGMA foreign_keys=ON`` enforces every FK,
        including the ones nothing was cascading before.
        """
        task = await self.get_task(task_id)
        if task is None:
            return False
        for child in task.children:
            child.parent_id = None
        cron_children = await self.session.execute(
            select(Task).where(Task.cron_template_id == task_id)
        )
        for clone in cron_children.scalars().all():
            clone.cron_template_id = None
        telemetry_rows = await self.session.execute(
            select(Telemetry).where(Telemetry.task_id == task_id)
        )
        for record in telemetry_rows.scalars().all():
            record.task_id = None
        await self.session.delete(task)
        await self.session.commit()
        return True

    # ------------------------------------------------------- DEQUEUE + DAG
    async def check_dependencies(self, task_id: str) -> bool:
        """Return True if every task this one depends on is ``completed``."""
        deps = await self.session.execute(
            select(TaskDependency.depends_on_id).where(
                TaskDependency.task_id == task_id
            )
        )
        dep_ids = [row[0] for row in deps.all()]
        if not dep_ids:
            return True
        completed = await self.session.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.id.in_(dep_ids), Task.status == "completed")
        )
        n_completed = completed.scalar_one()
        return n_completed == len(dep_ids)

    async def get_dependencies(self, task_id: str) -> dict:
        """Return the full dependency status tree for a task."""
        task = await self.get_task(task_id)
        if task is None:
            return {}

        depends_on = []
        for edge in task.dependencies_as_blocked:
            dep = edge.depends_on_task
            depends_on.append(
                {
                    "task_id": dep.id,
                    "title": dep.title,
                    "status": dep.status,
                    "completed": dep.status == "completed",
                }
            )

        # Tasks that this one blocks.
        blocked_rows = await self.session.execute(
            select(TaskDependency.task_id).where(
                TaskDependency.depends_on_id == task_id
            )
        )
        blocks_ids = [row[0] for row in blocked_rows.all()]
        blocks: list[dict] = []
        if blocks_ids:
            blocked_tasks = await self.session.execute(
                select(Task).where(Task.id.in_(blocks_ids))
            )
            for bt in blocked_tasks.scalars().all():
                blocks.append(
                    {"task_id": bt.id, "title": bt.title, "status": bt.status}
                )

        return {
            "task_id": task_id,
            "depends_on": depends_on,
            "blocks": blocks,
            "all_deps_completed": all(d["completed"] for d in depends_on),
        }

    async def get_ready_tasks(self, project_id: str) -> list[Task]:
        """Return ``not_started`` tasks whose dependencies are ALL completed."""
        candidates = await self.get_tasks_by_project(project_id, status="not_started")
        ready: list[Task] = []
        for task in candidates:
            if await self.check_dependencies(task.id):
                ready.append(task)
        return ready

    async def get_next_task(
        self, project_id: str, assignee: str = "agent"
    ) -> Task | None:
        """DEQUEUE: atomically claim the highest-priority ready ``not_started`` task.

        Uses the ``idx_tasks_dequeue`` composite index (project, assignee,
        status) for the base scan, then filters by DAG readiness. Claiming is
        a conditional ``UPDATE ... WHERE status = 'not_started'``, so when two
        agents race to dequeue at once only one of them can win a given task —
        the loser's update matches zero rows and it moves on to the next
        candidate instead of both starting duplicate work.
        """
        candidates = await self.session.execute(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.assignee == assignee,
                Task.status == "not_started",
            )
            .order_by(
                Task.priority.desc(), Task.sort_order, Task.created_at
            )
        )
        for (task_id,) in candidates.all():
            if not await self.check_dependencies(task_id):
                continue
            if await self._claim_task(task_id):
                return await self.get_task(task_id)
        return None

    async def _claim_task(self, task_id: str) -> bool:
        """Atomically transition a ``not_started`` task to ``ongoing``.

        Returns True iff this call won the claim (i.e. the row still had
        status ``not_started`` at update time).
        """
        result = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == "not_started")
            .values(status="ongoing", started_at=datetime.now(timezone.utc))
        )
        await self.session.commit()
        return result.rowcount == 1

    # ---------------------------------------------------- STATE MACHINE
    async def update_status(
        self,
        task_id: str,
        new_status: str,
        reason: str | None = None,
        actor: str = "system",
    ) -> Task:
        """Transition a task's status through the validated state machine.

        Raises :class:`ValueError` for invalid transitions.
        """
        task = await self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        old_status = task.status
        if new_status == old_status:
            return task  # idempotent no-op

        allowed = VALID_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {old_status} -> {new_status}"
            )

        now = datetime.now(timezone.utc)
        if new_status == "ongoing" and task.started_at is None:
            task.started_at = now
        if new_status == "completed":
            task.completed_at = now
        if new_status in {"ongoing"} and old_status == "completed":
            task.completed_at = None  # reopening

        task.status = new_status

        await self._record_telemetry(
            project_id=task.project_id,
            task_id=task.id,
            action="status_change",
            actor=actor,
            details={"from": old_status, "to": new_status, "reason": reason},
        )

        note = (
            f"Status changed from {old_status} to {new_status}"
            + (f": {reason}" if reason else "")
        )
        await self.add_message(
            task_id=task.id,
            author="system",
            content=note,
            message_type="system",
        )
        await self.session.commit()
        await self.session.refresh(task)

        await tracker.publish(
            task.project_id,
            "status_change",
            {
                "task_id": task.id,
                "from": old_status,
                "to": new_status,
                "title": task.title,
            },
        )

        if new_status == "completed" and task.emit_event_id:
            await self._fire_completion_event(task)

        return task

    async def _fire_completion_event(self, task: Task) -> None:
        """Publish a task's declared ``emit_event_id`` on completion.

        This is what makes ``emit_event_id`` actually drive cross-project
        choreography (see :class:`cascade.models.event.Event`) — without it,
        the field is inert metadata.
        """
        from cascade.models import Event
        from cascade.schemas.event import EventPublish
        from cascade.services.event_service import EventService

        event = await self.session.get(Event, task.emit_event_id)
        if event is None:
            return
        await EventService(self.session).publish_event(
            EventPublish(
                project_id=task.project_id,
                name=event.name,
                payload={"task_id": task.id, "title": task.title},
            )
        )

    # --------------------------------------------------------- MESSAGES
    async def add_message(
        self,
        task_id: str,
        author: str,
        content: str,
        message_type: str = "reply",
        metadata: dict | None = None,
    ) -> Message:
        """Append a message to the conversation log + broadcast via SSE.

        Raises :class:`ValueError` if ``task_id`` does not reference a real
        task — otherwise the message would be silently orphaned.
        """
        task = await self.session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        msg = Message(
            id=new_id(),
            task_id=task_id,
            author=author,
            content=content,
            message_type=message_type,
            metadata_json=dumps(metadata) if metadata else None,
        )
        self.session.add(msg)

        project_id = task.project_id
        await self._record_telemetry(
            project_id=project_id,
            task_id=task_id,
            action="message",
            actor=author,
            details={"message_type": message_type},
        )
        await self.session.commit()
        await self.session.refresh(msg)

        if project_id:
            await tracker.publish(
                project_id,
                "message",
                {
                    "task_id": task_id,
                    "author": author,
                    "content": content,
                    "message_type": message_type,
                },
            )
        return msg

    async def list_messages(self, task_id: str) -> list[Message]:
        """Return the conversation log for a task, oldest first."""
        result = await self.session.execute(
            select(Message)
            .where(Message.task_id == task_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------- TELEMETRY
    async def _record_telemetry(
        self,
        project_id: str | None,
        task_id: str | None,
        action: str,
        actor: str,
        details: dict | None = None,
    ) -> None:
        """Persist a telemetry audit record (does not commit on its own)."""
        self.session.add(
            Telemetry(
                project_id=project_id,
                task_id=task_id,
                action=action,
                actor=actor,
                details_json=dumps(details) if details else None,
            )
        )
