"""
Continuous Monitor Daemon — Runs alongside Cascade to detect and nudge stalled tasks.

Usage:
    python -m cascade.integrations.monitor_daemon --interval 10 --cascade-url http://localhost:8100

This implements the "continuous monitoring" improvement over AgentRQ's hourly nudge.
Instead of checking once per hour, it checks every 10 seconds and nudges tasks that
have been silent for more than 5 minutes.

How it works
------------
1. Every ``--interval`` seconds, list every active project from Cascade.
2. For each project, fetch all ``ongoing`` tasks and their conversation logs.
3. Compute per-task silence (time since the most recent message, falling back to
   the task's ``updated_at`` / ``started_at`` / ``created_at``).
4. Tasks silent longer than ``--stall-minutes`` get a nudge message
   (``message_type=system``), at most once per ``--nudge-cooldown`` per task.
5. Tasks silent longer than ``--critical-minutes`` additionally trigger a Slack
   alert (``--slack-webhook`` or ``SLACK_WEBHOOK_URL``), throttled to once per
   critical window per task.

Stall detection is computed *client-side* (independent of Cascade's own
``stall_threshold_minutes`` setting) so the daemon can react on a tighter cadence
than the in-process poller in ``cascade.engine.poller``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from cascade.integrations.hermes_bridge import CascadeAPIError, CascadeClient

logger = logging.getLogger("cascade.monitor_daemon")

__all__ = ["MonitorDaemon", "main"]

DEFAULT_CASCADE_URL = os.environ.get("CASCADE_URL", "http://localhost:8100")
DEFAULT_SLACK_WEBHOOK = (
    os.environ.get("SLACK_WEBHOOK_URL") or os.environ.get("CASCADE_SLACK_WEBHOOK")
)

# The canonical nudge text (kept stable so the orchestrator can recognise its own
# status-check probes when it later reads a task's conversation log).
NUDGE_TEXT = (
    "⏰ Status check: Are you still working on this? "
    "Please report your current progress."
)


def _parse_dt(value: Any) -> datetime:
    """Parse an ISO-8601 string (or pass through a datetime) into aware UTC."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class MonitorDaemon:
    """Continuously poll Cascade for stalled tasks and nudge them."""

    def __init__(
        self,
        cascade_url: str = DEFAULT_CASCADE_URL,
        *,
        interval: int = 10,
        stall_minutes: float = 5.0,
        critical_minutes: float = 30.0,
        nudge_cooldown: float | None = None,
        slack_webhook: str | None = None,
        client: CascadeClient | None = None,
    ) -> None:
        self.cascade_url = cascade_url.rstrip("/")
        self.interval = max(1, int(interval))
        self.stall_seconds = stall_minutes * 60.0
        self.critical_seconds = critical_minutes * 60.0
        # Re-nudge a given task at most once per stall window by default.
        self.nudge_cooldown = (
            nudge_cooldown if nudge_cooldown is not None else self.stall_seconds
        )
        self.slack_webhook = slack_webhook
        self._client = client if client is not None else CascadeClient(self.cascade_url)
        self._last_nudge: dict[str, float] = {}
        self._last_alert: dict[str, float] = {}
        self._consecutive_errors = 0
        self._running = True

    @property
    def client(self) -> CascadeClient:
        return self._client

    # ------------------------------------------------------------ lifecycle
    def stop(self) -> None:
        self._running = False

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
            except (NotImplementedError, RuntimeError, ValueError):
                # Not supported on this platform / no main thread — rely on
                # KeyboardInterrupt + the default asyncio SIGTERM handling.
                pass

    def _on_signal(self, sig: signal.Signals) -> None:
        logger.info("Received %s; shutting down after the current tick...", sig.name)
        self._running = False

    async def run(self) -> None:
        """Run the monitoring loop until stopped (SIGINT/SIGTERM)."""
        self._install_signal_handlers()
        logger.info(
            "Continuous monitor started — cascade=%s interval=%ss "
            "stall=%.1fmin critical=%.1fmin slack=%s",
            self.cascade_url,
            self.interval,
            self.stall_seconds / 60.0,
            self.critical_seconds / 60.0,
            bool(self.slack_webhook),
        )

        ready = await self._client.wait_for_ready(timeout=30.0)
        if not ready:
            logger.warning("Cascade not reachable yet; will keep retrying each tick.")

        while self._running:
            try:
                await self._tick()
                self._consecutive_errors = 0
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                # Cascade temporarily unavailable — back off and auto-reconnect.
                self._consecutive_errors += 1
                backoff = min(
                    60.0, self.interval * (2 ** min(self._consecutive_errors, 5))
                )
                logger.warning(
                    "Cascade unavailable (%s); retrying in %.0fs",
                    exc.__class__.__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)
                continue
            except CascadeAPIError:
                logger.exception("Cascade API error during monitor tick")
            except Exception:  # noqa: BLE001 - never let the daemon die
                logger.exception("Unexpected error during monitor tick")

            await asyncio.sleep(self.interval)

        logger.info("Continuous monitor stopped")
        await self._client.aclose()

    # ------------------------------------------------------------ ticks
    async def _tick(self) -> None:
        projects = await self._client.list_projects(status_filter="active")
        for project in projects or []:
            project_id = project.id
            name = getattr(project, "name", project_id)
            try:
                await self._check_project(project_id, name)
            except CascadeAPIError:
                logger.exception("API error while checking project %s (%s)", project_id, name)

    async def _check_project(self, project_id: str, project_name: str) -> None:
        ongoing = await self._client.list_tasks(project_id, status="ongoing")
        if not ongoing:
            return
        for task in ongoing:
            task_id = getattr(task, "id", None)
            try:
                await self._check_task(project_id, project_name, task)
            except CascadeAPIError:
                logger.exception("API error while checking task %s", task_id)

    async def _check_task(
        self, project_id: str, project_name: str, task: Any
    ) -> None:
        task_id = task.id
        title = getattr(task, "title", task_id)

        messages = await self._client.list_messages(task_id)
        silence = self._silence_seconds(task, messages)
        silence_min = silence / 60.0
        now = time.monotonic()

        # --- nudge (stalled) ---
        if silence >= self.stall_seconds:
            if (now - self._last_nudge.get(task_id, 0.0)) >= self.nudge_cooldown:
                try:
                    await self._client.add_message(
                        task_id,
                        NUDGE_TEXT,
                        message_type="system",
                        author="system",
                    )
                except CascadeAPIError:
                    logger.exception("Failed to nudge stalled task %s", task_id)
                else:
                    self._last_nudge[task_id] = now
                    logger.info(
                        "⏰ Nudged stalled task %s (%s) in '%s' — silent %.1f min",
                        task_id,
                        title,
                        project_name,
                        silence_min,
                    )

        # --- escalate (critical) ---
        if silence >= self.critical_seconds:
            if (now - self._last_alert.get(task_id, 0.0)) >= self.critical_seconds:
                await self._alert_critical(project_name, task, silence)
                self._last_alert[task_id] = now

    @staticmethod
    def _silence_seconds(task: Any, messages: Any) -> float:
        """Seconds since the task's last message (or last lifecycle timestamp)."""
        now = datetime.now(timezone.utc)
        last: datetime | None = None

        for message in messages or []:
            created = getattr(message, "created_at", None)
            if created:
                try:
                    parsed = _parse_dt(created)
                except (ValueError, TypeError):
                    continue
                if last is None or parsed > last:
                    last = parsed

        if last is None:
            # No messages: fall back to lifecycle timestamps.
            for key in ("updated_at", "started_at", "created_at"):
                value = getattr(task, key, None)
                if value:
                    try:
                        last = _parse_dt(value)
                        break
                    except (ValueError, TypeError):
                        continue

        if last is None:
            return 0.0
        return max(0.0, (now - last).total_seconds())

    async def _alert_critical(self, project_name: str, task: Any, silence_seconds: float) -> None:
        mins = silence_seconds / 60.0
        title = getattr(task, "title", task.id)
        text = (
            f"🚨 Cascade critical stall: task '{title}' (id={task.id}) "
            f"in project '{project_name}' has been silent for {mins:.0f} min."
        )
        logger.error(text)
        if not self.slack_webhook:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                resp = await http_client.post(self.slack_webhook, json={"text": text})
            if resp.status_code >= 400:
                logger.warning(
                    "Slack returned %s: %s", resp.status_code, resp.text[:200]
                )
        except Exception:  # noqa: BLE001 - notifications must never kill the daemon
            logger.warning("Slack notification failed", exc_info=True)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuous monitor daemon for stalled Cascade tasks."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Seconds between polls across all projects (default 10).",
    )
    parser.add_argument(
        "--cascade-url",
        default=DEFAULT_CASCADE_URL,
        help="Cascade base URL (default: env CASCADE_URL or http://localhost:8100).",
    )
    parser.add_argument(
        "--stall-minutes",
        type=float,
        default=5.0,
        help="Minutes of silence before nudging a task (default 5).",
    )
    parser.add_argument(
        "--critical-minutes",
        type=float,
        default=30.0,
        help="Minutes of silence before escalating to Slack (default 30).",
    )
    parser.add_argument(
        "--nudge-cooldown",
        type=float,
        default=None,
        help="Minimum seconds between nudges for the same task (default = stall window).",
    )
    parser.add_argument(
        "--slack-webhook",
        default=DEFAULT_SLACK_WEBHOOK,
        help="Optional Slack incoming-webhook URL (default: env SLACK_WEBHOOK_URL).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG/INFO/WARNING/ERROR).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    _setup_logging(args.log_level)
    daemon = MonitorDaemon(
        cascade_url=args.cascade_url,
        interval=args.interval,
        stall_minutes=args.stall_minutes,
        critical_minutes=args.critical_minutes,
        nudge_cooldown=args.nudge_cooldown,
        slack_webhook=args.slack_webhook,
    )
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
