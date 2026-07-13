"""Pinger — session keep-alive + dead-session eviction.

Runs on the monitoring loop to evict agent sessions whose last heartbeat
exceeds the configured timeout, so the dashboard's "agent alive" indicator
stays accurate.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from cascade.engine.progress_tracker import tracker
from cascade.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)


async def pinger_tick(session: AsyncSession) -> int:
    """Evict dead agent sessions and broadcast status changes via SSE.

    Returns the number of sessions evicted.
    """
    monitor_svc = MonitorService(session)
    # Snapshot BEFORE evicting: a project whose last session just died is
    # removed from ``_sessions`` entirely, so iterating the dict *after*
    # eviction would silently skip broadcasting its now-offline status.
    watched_projects = set(monitor_svc._sessions)  # noqa: SLF001
    evicted = await monitor_svc.evict_dead_sessions()
    if evicted:
        logger.info("Evicted %d dead agent session(s)", evicted)
        # Notify any dashboard subscribers that liveness may have changed.
        for project_id in watched_projects:
            alive = await monitor_svc.is_agent_alive(project_id)
            await tracker.publish(
                project_id, "agent_status", {"alive": alive, "evicted": evicted}
            )
    return evicted
