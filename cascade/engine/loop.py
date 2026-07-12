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


async def _tick() -> None:
    """Run one monitoring tick: poller + pinger + scheduler concurrently."""
    async with async_session_factory() as session:
        poller_task = asyncio.create_task(poller_tick(session))
        pinger_task = asyncio.create_task(pinger_tick(session))
        scheduler_task = asyncio.create_task(scheduler_tick())
        stall_task = asyncio.create_task(stall_detector_tick())
        try:
            await asyncio.gather(
                poller_task, pinger_task, scheduler_task, stall_task,
                return_exceptions=True,
            )
        finally:
            await session.commit()


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
