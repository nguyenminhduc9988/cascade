"""Tests for MonitorService + AutoDecisionService — liveness, stalls, autonomy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cascade.models import Project
from cascade.schemas.task import TaskCreate
from cascade.services.auto_decision import AutoDecisionService
from cascade.services.monitor_service import MonitorService
from cascade.services.task_service import TaskService


async def _project(session) -> Project:
    project = Project(id="01PROJECT0000000000000000003", name="Monitor")
    session.add(project)
    await session.commit()
    return project


@pytest.mark.asyncio
async def test_agent_liveness_register_and_evict(session):
    project = await _project(session)
    monitor = MonitorService(session)

    assert await monitor.is_agent_alive(project.id) is False
    await monitor.register_agent_session(project.id, "sess-1")
    assert await monitor.is_agent_alive(project.id) is True

    # Force the session into the past to trigger eviction.
    monitor._sessions[project.id]["sess-1"] = datetime.now(timezone.utc) - timedelta(
        hours=1
    )
    evicted = await monitor.evict_dead_sessions(timeout_seconds=1)
    assert evicted == 1
    assert await monitor.is_agent_alive(project.id) is False


@pytest.mark.asyncio
async def test_stalled_task_detection_and_nudge(session):
    from cascade.models import Message

    project = await _project(session)
    task_svc = TaskService(session)
    monitor = MonitorService(session)

    task = await task_svc.create_task(TaskCreate(project_id=project.id, title="slow"))
    await task_svc.update_status(task.id, "ongoing")

    # The status change leaves a recent system message; backdate all messages
    # so the task looks silent for longer than the threshold.
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    msgs = await session.execute(
        select(Message).where(Message.task_id == task.id)
    )
    for m in msgs.scalars().all():
        m.created_at = old
    await session.commit()

    stalled = await monitor.get_stalled_tasks(project.id, threshold_minutes=30)
    assert len(stalled) == 1
    assert stalled[0].id == task.id

    msg = await monitor.nudge_stalled_task(task.id)
    assert msg is not None
    assert "Stall check" in msg.content

    # A fresh message should make it no longer stalled.
    stalled = await monitor.get_stalled_tasks(project.id, threshold_minutes=30)
    assert len(stalled) == 0


@pytest.mark.asyncio
async def test_completion_check_heuristic(session):
    project = await _project(session)
    task_svc = TaskService(session)
    monitor = MonitorService(session)
    task = await task_svc.create_task(TaskCreate(project_id=project.id, title="T"))
    await task_svc.update_status(task.id, "ongoing")
    assert await monitor.check_completion(task.id) is False
    await task_svc.add_message(task.id, "agent", "All done, summary attached", "reply")
    assert await monitor.check_completion(task.id) is True


@pytest.mark.asyncio
async def test_auto_decision_picks_safest_choice(session):
    project = await _project(session)
    task_svc = TaskService(session)
    auto = AutoDecisionService(session)
    task = await task_svc.create_task(TaskCreate(project_id=project.id, title="T"))

    choices = [
        {"label": "risky", "risk": "high", "effort": "high", "reversible": False},
        {"label": "safe", "risk": "low", "effort": "low", "reversible": True},
    ]
    decision = await auto.auto_resolve_choice(task.id, choices)
    assert decision["chosen"]["label"] == "safe"

    msgs = await task_svc.list_messages(task.id)
    assert any("Auto-selected" in m.content for m in msgs)


def test_should_ask_human_only_for_destructive():
    svc = AutoDecisionService.__new__(AutoDecisionService)  # bypass session
    assert svc.should_ask_human("t1", "delete-database") is True
    assert svc.should_ask_human("t1", "production-deploy") is True
    assert svc.should_ask_human("t1", "choose-framework") is False
    assert svc.should_ask_human("t1", "rename-variable") is False
