"""Pytest fixtures — async in-memory SQLite for isolated service/API tests."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cascade import models  # noqa: F401 — register models
from cascade.database import Base, get_db
from cascade.main import app


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory SQLite engine per test.

    Mirrors production's ``PRAGMA foreign_keys=ON`` (see cascade/database.py)
    so tests actually exercise referential-integrity failures instead of
    silently tolerating dangling foreign keys that only surface in prod.
    """
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    @event.listens_for(eng.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    """Request-scoped async session."""
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine):
    """HTTPX async client wired to the FastAPI app with an in-memory DB."""
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
