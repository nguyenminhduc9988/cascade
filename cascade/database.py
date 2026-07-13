"""Async database engine, session factory and declarative Base.

Provides the single :data:`engine`, the :data:`async_session_factory` and the
dependency :func:`get_db` used by FastAPI route handlers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from cascade.config import settings


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy 2.0 typed models."""


engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

if engine.url.get_backend_name() == "sqlite":
    # The monitoring loop and API requests hit SQLite from several concurrent
    # connections. Without WAL + a busy timeout, SQLite's default rollback
    # journal serialises writers and raises "database is locked" almost
    # immediately under any real concurrency.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an :class:`AsyncSession`."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables. Intended for dev/bootstrap; Alembic is used in prod."""
    # Importing here ensures every model is registered on ``Base.metadata``.
    from cascade import models  # noqa: F401  (register models)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
