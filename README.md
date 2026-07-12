# 🌀 Cascade

**An agent task orchestration platform** that combines Leantime's *strategic
coherence* (task–goal–milestone links) with AgentRQ's *agent orchestration*
(dequeue, status state machine, MCP tools, continuous monitoring loop).

Cascade is a from-scratch Python reimplementation and significant improvement
of AgentRQ (Go), built on FastAPI + SQLAlchemy 2.0 with an HTMX/Tailwind UI and
real-time SSE updates.

---

## ✨ Highlights

- **Strategic coherence** — every task links explicitly to a goal and milestone;
  goal progress is *computed at read-time* from linked tasks (never denormalised).
- **Pull-based work queue** — agents dequeue the highest-priority `not_started`
  task whose DAG dependencies are all completed (`idx_tasks_dequeue` composite index).
- **Status state machine** — `not_started → ongoing → completed|blocked|rejected`,
  validated centrally in `TaskService.update_status`.
- **Continuous monitoring loop** — a 10-second tick (not hourly) runs the poller,
  pinger and scheduler concurrently; stalls are detected and nudged.
- **Autonomy-first** — `AutoDecisionService` resolves choices automatically and
  only escalates to a human for genuinely irreversible/destructive operations.
- **Cross-project choreography** — events + triggers materialise tasks on publish.
- **MCP agent tools** — `get_task`, `create_task`, `reply`, `update_status`,
  `get_mission`, `get_project_context`, `publish_event`, `get_dependencies`.
- **Real-time UI** — SSE-powered dashboard with agent liveness dots, goal
  progress bars, drag-and-drop Kanban, and per-task conversation logs.

---

## 🧱 Tech stack

| Concern        | Choice                                   |
|----------------|------------------------------------------|
| Runtime        | Python 3.11+, FastAPI, Uvicorn           |
| ORM            | SQLAlchemy 2.0 (async, `Mapped[]`) + aiosqlite |
| Migrations     | Alembic                                  |
| Schemas        | Pydantic v2                              |
| IDs            | `python-ulid` (time-ordered, sortable)   |
| Real-time      | `sse-starlette` + in-memory pub/sub      |
| Scheduling     | APScheduler + croniter (cron templates)  |
| UI             | HTMX + Tailwind (CDN, no build step)     |
| Templating     | Jinja2                                   |

---

## 🚀 Quick start

```bash
# from /home/minguyen/.hermes
cd cascade

# run with the project venv
hermes-agent/venv/bin/python -m uvicorn cascade.main:app --reload --port 8100
```

Open **http://localhost:8100** for the dashboard. The API docs are at
`/docs`, and `/api/health` reports service health.

On first boot the database is created automatically (`init_db`). For managed
schema changes, use Alembic:

```bash
hermes-agent/venv/bin/python -m alembic upgrade head
hermes-agent/venv/bin/python -m alembic revision --autogenerate -m "describe change"
```

---

## 🗂️ Project structure

```
cascade/
├── pyproject.toml          # dependencies + pytest config
├── alembic.ini             # migration config (async)
├── alembic/                # env.py + versions/
├── cascade/
│   ├── main.py             # FastAPI app factory + lifespan (monitoring loop)
│   ├── config.py           # Pydantic Settings (CASCADE_ env prefix)
│   ├── database.py         # async engine, session factory, Base
│   ├── utils.py            # ULID + JSON helpers
│   ├── models/             # SQLAlchemy 2.0 typed models
│   ├── schemas/            # Pydantic v2 request/response
│   ├── services/           # business logic (thin controllers → services)
│   ├── routers/            # FastAPI route handlers (REST + SSE + HTMX pages)
│   ├── mcp/                # MCP server factory + tools + agent instructions
│   ├── engine/             # monitoring loop, poller, pinger, progress tracker
│   └── web/                # Jinja2 templates + static app.js
└── tests/                  # pytest-asyncio (23 tests)
```

---

## 🧠 Data model (the core)

```
Project ─┬─< Goal ────< Task
         ├─< Milestone─< Task
         └─< Task >─ TaskDependency (DAG edges)
                    > Message (append-only conversation)
                    > Telemetry (audit trail)
Event / EventTrigger ── publish ──> auto-create Task
```

`Task` is the **unified work item** (polymorphic: epic/story/task/subtask) with
a status state machine, bidirectional human/agent delegation, self-referential
hierarchy, strategic goal/milestone links, cron-template spawning and event
choreography — a single model doing what Leantime spreads across many.

---

## ⚙️ Key behaviours

### Dequeue (agent pull queue)
`GET /api/tasks/dequeue?project_id=…&assignee=agent` returns the highest-priority
`not_started` task whose every `depends_on` is `completed`. Backed by the
`idx_tasks_dequeue (project_id, assignee, status)` composite index.

### Status state machine
All transitions go through `TaskService.update_status`, which validates against
`VALID_TRANSITIONS`, sets `started_at`/`completed_at`, records telemetry, posts
a system message and broadcasts an SSE `status_change` event.

### Goal progress (read-time)
`GoalService.get_progress` counts linked tasks completed/total when
`auto_aggregate` is True — progress is **never stored/denormalised**.

### Continuous monitoring loop
`engine/loop.monitoring_loop` runs every **10 seconds**, concurrently executing
the poller (stall nudging), pinger (dead-session eviction) and scheduler (cron
template spawning). Stall detection runs on its own slower cadence.

### Autonomy
`AutoDecisionService.should_ask_human` returns `True` only for destructive
operations (`delete`, `drop`, `production-deploy`, …); everything else is
auto-resolved via `auto_resolve_choice` (prefers low-risk, low-effort,
reversible options).

---

## 🤖 MCP tools

| Tool                | Purpose                                          |
|---------------------|--------------------------------------------------|
| `get_task`          | Dequeue next task (no ID) or fetch a specific one|
| `create_task`       | Decompose / delegate (parent_id + depends_on)    |
| `reply`             | Post progress/reply/permission messages          |
| `update_status`     | Transition task status                           |
| `get_mission`       | Big-picture mission + active goals               |
| `get_project_context` | Full project state for coherence               |
| `publish_event`     | Emit a cross-project choreography event          |
| `get_dependencies`  | Dependency tree status                           |
| `auto_decide`       | Auto-resolve a choice                            |

See [`cascade/mcp/instructions.py`](cascade/mcp/instructions.py:1) for the
agent operating contract served as the MCP server instructions.

---

## 🧪 Tests

```bash
cd cascade
hermes-agent/venv/bin/python -m pytest -q
```

23 tests cover the task state machine + dequeue + DAG resolution, goal progress
aggregation, agent liveness/stall detection, auto-decision, and the REST API +
HTMX page rendering (isolated in-memory SQLite per test).

---

## 🔧 Configuration

All settings are overridable via `CASCADE_`-prefixed env vars or a `.env` file
(see [`cascade/config.py`](cascade/config.py:1)):

| Setting                         | Default                  |
|---------------------------------|--------------------------|
| `CASCADE_DATABASE_URL`          | `sqlite+aiosqlite:///./cascade.db` |
| `CASCADE_PORT`                  | `8100`                   |
| `CASCADE_LOOP_TICK_SECONDS`     | `10`                     |
| `CASCADE_STALL_THRESHOLD_MINUTES` | `30`                   |
| `CASCADE_SESSION_TIMEOUT_SECONDS` | `60`                   |
| `CASCADE_ENABLE_MONITORING_LOOP` | `true`                  |

---

## 🛠️ Development

### Install dev dependencies

```bash
cd cascade
hermes-agent/venv/bin/pip install -e ".[dev]"
```

### Run the test suite

```bash
hermes-agent/venv/bin/python -m pytest -q
```

Tests use `pytest-asyncio` with an isolated in-memory SQLite database per test,
so they are fast and side-effect-free. Coverage spans the task state machine and
dequeue/DAG resolution, goal progress aggregation, agent liveness and stall
detection, the auto-decision engine, and the REST API + HTMX page rendering.

### Architecture notes

- **Thin controllers → services.** Routers only parse + serialise; all business
  logic lives in the `services/` package, keeping endpoints trivial to test.
- **Read-time aggregation.** Goal progress is *computed* on read (never stored),
  so there is no denormalisation drift to repair.
- **Centralised state transitions.** Every status change funnels through
  `TaskService.update_status`, which enforces `VALID_TRANSITIONS` and records
  telemetry + SSE broadcasts in one place.

### Database migrations

Schema changes are managed with Alembic. Create a new revision, review the
autogenerated diff, then upgrade:

```bash
hermes-agent/venv/bin/python -m alembic revision --autogenerate -m "add new table"
hermes-agent/venv/bin/python -m alembic upgrade head
```

### Contributing

1. Fork the repo and create a feature branch.
2. Add or update tests for any behaviour change.
3. Ensure `pytest -q` passes and no lint regressions.
4. Open a pull request describing the change and its rationale.

---

## 📄 License

Released under the **MIT License** — see [`LICENSE`](LICENSE:1).

Cascade reinterprets ideas from [Leantime](https://github.com/Leantime/leantime)
(strategic task–goal–milestone coherence) and AgentRQ (agent dequeue + status
state machine + monitoring loop), reimplemented from scratch in Python. It is an
independent work and is not affiliated with or endorsed by either project.
