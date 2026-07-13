"""Main monitoring loop — continuous execution (10s tick, NOT hourly).

Runs forever (as a background task on app startup) and, on every tick, runs
the poller, pinger and scheduler concurrently. Stall detection runs on its own
slower cadence. This is the AgentRQ loop, reimagined as continuous monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import time

from cascade.config import settings
from cascade.database import async_session_factory
from cascade.engine.pinger import pinger_tick
from cascade.engine.poller import poller_tick
from cascade.services.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)

# Module-level state so the loop can be stopped gracefully.
_running = False
_last_stall_check = 0.0


async def scheduler_tick() -> int:
    """Process due cron templates, returning spawned task count."""
    async with async_session_factory() as session:
        svc = SchedulerService(session)
        spawned = await svc.process_cron_templates()
    if spawned:
        logger.info("Scheduler spawned %d cron task(s)", len(spawned))
    return len(spawned)


async def stall_detector_tick() -> int:
    """Run stall detection on its own slower cadence (every 5 min)."""
    global _last_stall_check
    now = time.time()
    if now - _last_stall_check < settings.stall_check_interval_seconds:
        return 0
    _last_stall_check = now
    async with async_session_factory() as session:
        return await poller_tick(session)


async def _poller_tick_isolated() -> int:
    """Run the poller in its own session (never share one across concurrent ticks)."""
    async with async_session_factory() as session:
        result = await poller_tick(session)
        await session.commit()
        return result


async def _pinger_tick_isolated() -> int:
    """Run the pinger in its own session (never share one across concurrent ticks)."""
    async with async_session_factory() as session:
        result = await pinger_tick(session)
        await session.commit()
        return result


async def _tick() -> None:
    """Run one monitoring tick: poller + pinger + scheduler concurrently.

    Each concurrent piece of work gets its own :class:`AsyncSession` —
    ``AsyncSession`` is not safe for concurrent use by multiple coroutines,
    so sharing one across ``asyncio.gather`` would corrupt session state.
    """
    results = await asyncio.gather(
        _poller_tick_isolated(),
        _pinger_tick_isolated(),
        scheduler_tick(),
        stall_detector_tick(),
        return_exceptions=True,
    )
    for name, result in zip(
        ("poller", "pinger", "scheduler", "stall_detector"), results
    ):
        if isinstance(result, BaseException):
            logger.error("Monitoring tick component %r failed: %s", name, result)


async def monitoring_loop() -> None:
    """Main loop that runs forever, monitoring all projects every 10s."""
    global _running
    _running = True
    logger.info("Cascade monitoring loop started (tick=%ss)", settings.loop_tick_seconds)
    while _running:
        try:
            await _tick()
        except Exception:  # pragma: no cover - never let the loop die
            logger.exception("Monitoring tick failed")
        await asyncio.sleep(settings.loop_tick_seconds)
    logger.info("Cascade monitoring loop stopped")


def stop_monitoring_loop() -> None:
    """Signal the monitoring loop to stop after the current tick."""
    global _running
    _running = False


__all__ = ["monitoring_loop", "stop_monitoring_loop", "scheduler_tick"]
