"""Cascade application factory + entry point.

Wires together all routers, mounts static assets, initialises the database and
launches the continuous monitoring loop on startup.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from cascade.config import settings
from cascade.database import init_db
from cascade.engine.loop import monitoring_loop, stop_monitoring_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("cascade")

_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB + start the monitoring loop."""
    logger.info("Initialising database...")
    await init_db()

    loop_task = None
    if settings.enable_monitoring_loop:
        import asyncio

        loop_task = asyncio.create_task(monitoring_loop())

    logger.info("Cascade is ready at http://%s:%s", settings.host, settings.port)
    try:
        yield
    finally:
        if loop_task:
            stop_monitoring_loop()
            loop_task.cancel()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="Cascade",
        description=(
            "Agent task orchestration platform combining Leantime's strategic "
            "coherence with AgentRQ's agent orchestration."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # No cookie-based auth is used (Bearer tokens only), so a wildcard origin
    # is safe here — pairing it with allow_credentials=True would not be.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST + SSE routers
    from cascade.routers import dashboard, events, goals, milestones, projects, tasks
    from cascade.routers.pages import router as pages_router

    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(goals.router)
    app.include_router(milestones.router)
    app.include_router(events.router)
    app.include_router(dashboard.router)
    app.include_router(pages_router)

    # Static assets (SSE client, HTMX extensions)
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/api/health")
    async def health() -> dict:
        """Health check."""
        return {"status": "ok", "service": "cascade"}

    @app.get("/api/tools")
    async def list_mcp_tools() -> dict:
        """List the MCP agent tools."""
        from cascade.mcp.tools import TOOLS_REGISTRY

        return {
            name: spec["description"] for name, spec in TOOLS_REGISTRY.items()
        }

    return app


app = create_app()


def run() -> None:
    """Entry point for the ``cascade`` console script."""
    import uvicorn

    uvicorn.run(
        "cascade.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


if __name__ == "__main__":
    run()
