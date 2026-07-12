"""Real-time progress aggregation + SSE broadcasting broker.

An in-memory pub/sub keyed by project. SSE clients subscribe to a project's
queue via :meth:`ProgressTracker.subscribe`; services publish events via
:meth:`ProgressTracker.publish` which fans out to every subscriber.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)


class ProgressTracker:
    """In-memory broadcast broker for Server-Sent Events."""

    def __init__(self) -> None:
        # project_id -> list of asyncio.Queue
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    def subscribe(self, project_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber queue for ``project_id``."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers[project_id].append(queue)
        logger.debug("SSE subscriber added for project %s", project_id)
        return queue

    def unsubscribe(self, project_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a previously-registered subscriber queue."""
        if project_id in self._subscribers:
            try:
                self._subscribers[project_id].remove(queue)
            except ValueError:
                pass
            if not self._subscribers[project_id]:
                del self._subscribers[project_id]

    async def publish(self, project_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all subscribers of ``project_id``."""
        message = {"event": event_type, "data": {**data, "project_id": project_id}}
        for queue in list(self._subscribers.get(project_id, [])):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for project %s; dropping event", project_id)

    async def stream(self, project_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Yield events for ``project_id`` until the subscriber disconnects."""
        queue = self.subscribe(project_id)
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(project_id, queue)


# Module-level singleton used across services and routers.
tracker = ProgressTracker()
