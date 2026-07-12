"""Integration tests for the FastAPI REST API."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_project_crud(client):
    res = await client.post(
        "/api/projects",
        json={"name": "API Project", "mission": "test mission"},
    )
    assert res.status_code == 201
    project = res.json()
    pid = project["id"]

    res = await client.get("/api/projects")
    assert res.status_code == 200
    assert any(p["id"] == pid for p in res.json())

    res = await client.get(f"/api/projects/{pid}")
    assert res.status_code == 200
    assert res.json()["name"] == "API Project"

    res = await client.get(f"/api/projects/{pid}/mission")
    assert res.status_code == 200
    assert res.json()["mission"] == "test mission"


@pytest.mark.asyncio
async def test_task_create_dequeue_and_status(client):
    pid = (await client.post("/api/projects", json={"name": "P"})).json()["id"]

    res = await client.post(
        "/api/tasks", json={"project_id": pid, "title": "task one", "priority": 5}
    )
    assert res.status_code == 201
    task_one = res.json()

    await client.post(
        "/api/tasks", json={"project_id": pid, "title": "task two", "priority": 1}
    )

    # Dequeue returns the highest priority ready task.
    res = await client.get(f"/api/tasks/dequeue?project_id={pid}")
    assert res.status_code == 200
    assert res.json()["id"] == task_one["id"]

    # Transition status via the state machine.
    res = await client.patch(
        f"/api/tasks/{task_one['id']}/status?actor=agent",
        json={"status": "ongoing"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ongoing"

    res = await client.patch(
        f"/api/tasks/{task_one['id']}/status?actor=agent",
        json={"status": "completed"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_invalid_status_transition_returns_409(client):
    pid = (await client.post("/api/projects", json={"name": "P"})).json()["id"]
    task = (await client.post("/api/tasks", json={"project_id": pid, "title": "t"})).json()
    res = await client.patch(
        f"/api/tasks/{task['id']}/status?actor=agent",
        json={"status": "completed"},  # not_started -> completed is invalid
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_goal_progress_endpoint(client):
    pid = (await client.post("/api/projects", json={"name": "P"})).json()["id"]
    goal = (
        await client.post(
            "/api/goals",
            json={"project_id": pid, "title": "G", "target_value": 1.0},
        )
    ).json()
    task = (
        await client.post(
            "/api/tasks",
            json={"project_id": pid, "title": "t", "goal_id": goal["id"]},
        )
    ).json()
    await client.patch(
        f"/api/tasks/{task['id']}/status?actor=agent", json={"status": "ongoing"}
    )
    await client.patch(
        f"/api/tasks/{task['id']}/status?actor=agent", json={"status": "completed"}
    )

    res = await client.get(f"/api/goals/{goal['id']}/progress")
    assert res.status_code == 200
    body = res.json()
    assert body["task_completed"] == 1
    assert body["percentage"] == 100.0


@pytest.mark.asyncio
async def test_messages_endpoint(client):
    pid = (await client.post("/api/projects", json={"name": "P"})).json()["id"]
    task = (await client.post("/api/tasks", json={"project_id": pid, "title": "t"})).json()
    res = await client.post(
        f"/api/tasks/{task['id']}/messages",
        json={"task_id": task["id"], "author": "agent", "content": "hi", "message_type": "progress"},
    )
    assert res.status_code == 200
    res = await client.get(f"/api/tasks/{task['id']}/messages")
    assert res.status_code == 200
    assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_dashboard_overview_and_tools(client):
    res = await client.get("/api/dashboard/overview")
    assert res.status_code == 200
    res = await client.get("/api/tools")
    assert res.status_code == 200
    tools = res.json()
    assert "get_task" in tools
    assert "create_task" in tools


@pytest.mark.asyncio
async def test_pages_render(client):
    pid = (await client.post("/api/projects", json={"name": "P"})).json()["id"]
    res = await client.get("/")
    assert res.status_code == 200
    assert "Cascade" in res.text
    res = await client.get(f"/projects/{pid}")
    assert res.status_code == 200
