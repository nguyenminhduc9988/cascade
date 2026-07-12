"""
Cascade-Hermes Bridge — Connects the Hermes agent to the Cascade task
orchestration platform.

This is a thin, dependency-light async client over Cascade's REST API. It is
intentionally self-contained (only ``httpx`` + the standard library) so it can
be imported from the Hermes agent without pulling in the whole FastAPI stack.

Usage from the Hermes orchestrator
----------------------------------
.. code-block:: python

    import asyncio
    from cascade.integrations.hermes_bridge import CascadeClient

    async def main():
        client = CascadeClient(base_url="http://localhost:8100")

        # Create a project for a major task
        project = await client.create_project(name="Build Trading Bot", mission="...")

        # Create goals and tasks
        goal = await client.create_goal(project_id=project.id, title="Core Engine", target_value=100)
        task = await client.create_task(
            project_id=project.id, title="Implement order execution", goal_id=goal.id
        )

        # Update status as work progresses
        await client.update_task_status(task.id, "ongoing")
        await client.add_message(task.id, "Starting implementation...", message_type="progress")

        # Check task readiness (DAG dependencies)
        ready = await client.get_ready_tasks(project.id)

        # Get big-picture context
        context = await client.get_project_context(project.id)

        await client.aclose()

    asyncio.run(main())

Endpoint mapping notes
----------------------
The method names intentionally mirror the original design; a few target the
real Cascade endpoints, which differ slightly from a naive REST mapping:

* ``get_next_task``       -> ``GET /api/tasks/dequeue?project_id=...``
* ``get_ready_tasks``     -> ``GET /api/tasks/ready?project_id=...``
* ``get_project_context`` -> ``GET /api/dashboard/aggregate?project_id=...``
  (returns goals, milestones, task-status counts, stalled tasks, recent activity)
* ``get_stalled_tasks``   -> derived from the dashboard aggregate
* ``publish_event``       -> ``POST /api/events/publish``
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Mapping

import httpx

logger = logging.getLogger("cascade.hermes_bridge")

__all__ = ["CascadeClient", "CascadeAPIError", "DotDict"]

# --- Cascade domain constants (mirrors cascade/schemas/*.py) -----------------

#: Valid task statuses (state machine states).
TASK_STATUSES = {
    "not_started",
    "ongoing",
    "completed",
    "blocked",
    "rejected",
    "cron",
}

#: Valid task types.
TASK_TYPES = {"epic", "story", "task", "subtask"}

#: Valid message types for the append-only task conversation log.
MESSAGE_TYPES = {
    "reply",
    "progress",
    "permission_request",
    "permission_response",
    "system",
    "error",
}


class CascadeAPIError(Exception):
    """Raised when Cascade returns a non-2xx HTTP response."""

    def __init__(self, status_code: int, message: str, url: str) -> None:
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(f"[{status_code}] {url}: {message}")


def _wrap(value: Any) -> Any:
    """Recursively wrap dicts/lists so nested structures support attribute access."""
    if isinstance(value, DotDict):
        return value
    if isinstance(value, dict):
        return DotDict(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


class DotDict(dict):
    """A dict that also supports attribute-style access.

    ``d["id"]`` and ``d.id`` are equivalent, and nested dicts/lists are wrapped
    on access so ``project.mission`` and ``context.goals[0].title`` both work.
    The object remains a plain (JSON-serialisable) dict, so ``dict(d)``,
    ``json.dumps(d)`` and ``d.items()`` all behave normally.

    Note: because it subclasses ``dict``, a key whose name collides with a dict
    method (e.g. ``items``) is reachable via ``d["items"]`` rather than
    ``d.items``. No Cascade response field uses such names, so this is a
    non-issue in practice.
    """

    def __getattr__(self, key: str) -> Any:
        try:
            return _wrap(dict.__getitem__(self, key))
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def __getitem__(self, key):  # type: ignore[override]
        return _wrap(dict.__getitem__(self, key))


def _to_obj(data: Any) -> Any:
    """Coerce parsed JSON into DotDict-friendly shapes."""
    if data is None:
        return None
    if isinstance(data, list):
        return [_to_obj(item) for item in data]
    if isinstance(data, dict):
        return DotDict(data)
    return data


def _drop_none(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values from a params mapping (FastAPI treats them as absent)."""
    if params is None:
        return None
    return {key: value for key, value in params.items() if value is not None}


def _coerce_datetime(value: Any) -> str | None:
    """Normalise a date/datetime/str into an ISO-8601 string for JSON bodies."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _validate_choice(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(
            f"Invalid {label} {value!r}; must be one of {sorted(allowed)}"
        )
    return value


def _metadata_json(metadata: Any) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, str):
        return metadata
    return json.dumps(metadata)


class CascadeClient:
    """Async client for the Cascade task orchestration API.

    All mutating/listing methods return parsed JSON wrapped as :class:`DotDict`
    (or ``None`` for empty/dequeue responses). The underlying ``httpx.AsyncClient``
    is created lazily and reused; close it with :meth:`aclose` or use the async
    context manager.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8100",
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        if headers:
            self._headers.update(dict(headers))

    # ------------------------------------------------------------------ transport
    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self._headers,
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "CascadeClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        client = await self._ensure_client()
        url = path if path.startswith("http") else f"{self.base_url}/api{path}"
        try:
            resp = await client.request(
                method, url, params=_drop_none(params), json=json_body
            )
        except httpx.HTTPError:
            # Connection / timeout errors propagate so callers (e.g. the daemon)
            # can implement retry/backoff.
            raise
        if resp.status_code == 204 or not resp.content:
            return None
        if resp.status_code >= 400:
            raise CascadeAPIError(resp.status_code, resp.text, str(resp.url))
        try:
            return _to_obj(resp.json())
        except ValueError:  # pragma: no cover - non-JSON 2xx body
            return resp.text

    # ------------------------------------------------------------------ health
    async def health(self) -> Any:
        """``GET /api/health`` — returns ``{"status": "ok", ...}``."""
        return await self._request("GET", "/health")

    async def wait_for_ready(
        self, *, timeout: float = 30.0, interval: float = 1.0
    ) -> bool:
        """Poll ``/api/health`` until Cascade responds or ``timeout`` elapses.

        Returns ``True`` once Cascade is reachable, ``False`` on timeout.
        Connection errors during the wait are swallowed and retried.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                await self.health()
                return True
            except Exception:  # noqa: BLE001 - any transport/HTTP error retries
                await asyncio.sleep(interval)
        return False

    # ------------------------------------------------------------------ projects
    async def create_project(
        self,
        name: str,
        description: str | None = None,
        mission: str | None = None,
        *,
        status: str = "active",
    ) -> Any:
        """``POST /api/projects`` — create a project for a major request."""
        return await self._request(
            "POST",
            "/projects",
            json_body={
                "name": name,
                "description": description,
                "mission": mission,
                "status": status,
            },
        )

    async def list_projects(self, status_filter: str | None = None) -> Any:
        """``GET /api/projects`` — list projects, optionally filtered by status."""
        return await self._request(
            "GET", "/projects", params={"status_filter": status_filter}
        )

    async def get_project(self, project_id: str) -> Any:
        """``GET /api/projects/{id}``."""
        return await self._request("GET", f"/projects/{project_id}")

    async def get_mission(self, project_id: str) -> Any:
        """``GET /api/projects/{id}/mission`` — the agent big-picture brief."""
        return await self._request("GET", f"/projects/{project_id}/mission")

    # ------------------------------------------------------------------ goals
    async def create_goal(
        self,
        project_id: str,
        title: str,
        description: str | None = None,
        *,
        target_value: float = 100.0,
        metric_name: str | None = None,
        auto_aggregate: bool = True,
        status: str = "active",
    ) -> Any:
        """``POST /api/goals`` — create a strategic goal."""
        return await self._request(
            "POST",
            "/goals",
            json_body={
                "project_id": project_id,
                "title": title,
                "description": description,
                "target_value": target_value,
                "metric_name": metric_name,
                "auto_aggregate": auto_aggregate,
                "status": status,
            },
        )

    async def list_goals(self, project_id: str) -> Any:
        """``GET /api/goals?project_id=``."""
        return await self._request("GET", "/goals", params={"project_id": project_id})

    async def get_goal(self, goal_id: str) -> Any:
        """``GET /api/goals/{id}``."""
        return await self._request("GET", f"/goals/{goal_id}")

    async def get_goal_progress(self, goal_id: str) -> Any:
        """``GET /api/goals/{id}/progress`` — real-time computed progress.

        Returns ``{percentage, current_value, target_value, task_total,
        task_completed, status}``.
        """
        return await self._request("GET", f"/goals/{goal_id}/progress")

    async def list_goal_progress(self, project_id: str) -> Any:
        """``GET /api/goals/progress?project_id=`` — progress for every goal."""
        return await self._request(
            "GET", "/goals/progress", params={"project_id": project_id}
        )

    # ------------------------------------------------------------------ milestones
    async def create_milestone(
        self,
        project_id: str,
        title: str,
        description: str | None = None,
        start_date: Any = None,
        end_date: Any = None,
        *,
        status: str = "planned",
    ) -> Any:
        """``POST /api/milestones`` — ``start_date``/``end_date`` accept ISO str or datetime."""
        return await self._request(
            "POST",
            "/milestones",
            json_body={
                "project_id": project_id,
                "title": title,
                "description": description,
                "start_date": _coerce_datetime(start_date),
                "end_date": _coerce_datetime(end_date),
                "status": status,
            },
        )

    async def list_milestones(self, project_id: str) -> Any:
        """``GET /api/milestones?project_id=``."""
        return await self._request(
            "GET", "/milestones", params={"project_id": project_id}
        )

    # ------------------------------------------------------------------ tasks
    async def create_task(
        self,
        project_id: str,
        title: str,
        description: str | None = None,
        *,
        type: str = "task",
        goal_id: str | None = None,
        milestone_id: str | None = None,
        parent_id: str | None = None,
        depends_on: list[str] | None = None,
        priority: int = 0,
        assignee: str = "agent",
        created_by: str = "agent",
        status: str = "not_started",
        story_points: int | None = None,
        estimated_hours: float | None = None,
    ) -> Any:
        """``POST /api/tasks`` — create a task with optional DAG dependencies.

        ``depends_on`` is a list of task IDs that must complete before this one
        becomes ready.
        """
        _validate_choice(type, TASK_TYPES, "type")
        return await self._request(
            "POST",
            "/tasks",
            json_body={
                "project_id": project_id,
                "title": title,
                "description": description,
                "type": type,
                "goal_id": goal_id,
                "milestone_id": milestone_id,
                "parent_id": parent_id,
                "depends_on": depends_on,
                "priority": priority,
                "assignee": assignee,
                "created_by": created_by,
                "status": status,
                "story_points": story_points,
                "estimated_hours": estimated_hours,
            },
        )

    async def list_tasks(
        self,
        project_id: str,
        *,
        status: str | None = None,
        goal_id: str | None = None,
        milestone_id: str | None = None,
        parent_id: str | None = None,
    ) -> Any:
        """``GET /api/tasks`` — list tasks for a project with optional filters."""
        return await self._request(
            "GET",
            "/tasks",
            params={
                "project_id": project_id,
                "status": status,
                "goal_id": goal_id,
                "milestone_id": milestone_id,
                "parent_id": parent_id,
            },
        )

    async def get_task(self, task_id: str) -> Any:
        """``GET /api/tasks/{id}`` — full task with conversation + dependency context."""
        return await self._request("GET", f"/tasks/{task_id}")

    async def get_next_task(self, project_id: str, *, assignee: str = "agent") -> Any:
        """``GET /api/tasks/dequeue?project_id=`` — pull the next ready task.

        Returns the task, or ``None`` when no ready work remains.
        """
        return await self._request(
            "GET",
            "/tasks/dequeue",
            params={"project_id": project_id, "assignee": assignee},
        )

    async def get_ready_tasks(self, project_id: str) -> Any:
        """``GET /api/tasks/ready?project_id=`` — not_started tasks whose deps completed."""
        return await self._request(
            "GET", "/tasks/ready", params={"project_id": project_id}
        )

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        reason: str | None = None,
        actor: str = "agent",
    ) -> Any:
        """``PATCH /api/tasks/{id}/status`` — transition through the state machine."""
        _validate_choice(status, TASK_STATUSES, "status")
        return await self._request(
            "PATCH",
            f"/tasks/{task_id}/status",
            params={"actor": actor},
            json_body={"status": status, "reason": reason},
        )

    async def delete_task(self, task_id: str) -> None:
        """``DELETE /api/tasks/{id}``."""
        await self._request("DELETE", f"/tasks/{task_id}")

    async def get_dependencies(self, task_id: str) -> Any:
        """``GET /api/tasks/{id}/dependencies`` — the depends_on/blocks tree."""
        return await self._request("GET", f"/tasks/{task_id}/dependencies")

    async def add_message(
        self,
        task_id: str,
        content: str,
        *,
        message_type: str = "progress",
        author: str = "agent",
        metadata: Any = None,
    ) -> Any:
        """``POST /api/tasks/{id}/messages`` — append to the conversation log."""
        _validate_choice(message_type, MESSAGE_TYPES, "message_type")
        return await self._request(
            "POST",
            f"/tasks/{task_id}/messages",
            json_body={
                "task_id": task_id,
                "content": content,
                "message_type": message_type,
                "author": author,
                "metadata_json": _metadata_json(metadata),
            },
        )

    async def list_messages(self, task_id: str) -> Any:
        """``GET /api/tasks/{id}/messages`` — the full conversation log."""
        return await self._request("GET", f"/tasks/{task_id}/messages")

    # ------------------------------------------------------------------ events
    async def publish_event(
        self,
        project_id: str,
        event_name: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        """``POST /api/events/publish`` — publish a live event (fires triggers)."""
        return await self._request(
            "POST",
            "/events/publish",
            json_body={
                "project_id": project_id,
                "name": event_name,
                "payload": dict(payload) if payload else None,
            },
        )

    async def create_event(
        self,
        project_id: str,
        name: str,
        description: str | None = None,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        """``POST /api/events`` — define a named event for cross-project choreography."""
        return await self._request(
            "POST",
            "/events",
            json_body={
                "project_id": project_id,
                "name": name,
                "description": description,
                "payload": dict(payload) if payload else None,
            },
        )

    # ------------------------------------------------------------------ dashboard
    async def get_project_context(self, project_id: str) -> Any:
        """``GET /api/dashboard/aggregate?project_id=`` — the big-picture view.

        Returns project, goals, milestones, task-status counts, stalled tasks
        and recent activity. This is the strategic-coherence context the
        orchestrator consults to keep subtasks aligned with the mission.
        """
        return await self._request(
            "GET", "/dashboard/aggregate", params={"project_id": project_id}
        )

    async def get_stalled_tasks(self, project_id: str) -> Any:
        """Stalled ``ongoing`` tasks for a project (derived from the aggregate)."""
        context = await self.get_project_context(project_id)
        if not context:
            return []
        return context.get("stalled_tasks", []) or []

    async def get_overview(self) -> Any:
        """``GET /api/dashboard/overview`` — every project + live agent count."""
        return await self._request("GET", "/dashboard/overview")

    async def register_agent(self, project_id: str, session_id: str) -> Any:
        """``POST /api/dashboard/agents/{project_id}/register`` — green dot on."""
        return await self._request(
            "POST",
            f"/dashboard/agents/{project_id}/register",
            params={"session_id": session_id},
        )

    async def heartbeat(self, project_id: str, session_id: str) -> Any:
        """``POST /api/dashboard/agents/{project_id}/heartbeat`` — keep alive."""
        return await self._request(
            "POST",
            f"/dashboard/agents/{project_id}/heartbeat",
            params={"session_id": session_id},
        )
