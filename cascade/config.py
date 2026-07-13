"""Application configuration via Pydantic Settings.

All settings can be overridden with environment variables prefixed ``CASCADE_``
(e.g. ``CASCADE_PORT=8100``) or via a ``.env`` file in the working directory.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Cascade platform."""

    model_config = SettingsConfigDict(
        env_prefix="CASCADE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./cascade.db"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8100
    reload: bool = True

    # --- Engine ---
    # Seconds between monitoring-loop ticks. Continuous monitoring, not hourly.
    loop_tick_seconds: int = 10
    # Minutes of silence before an ongoing task is considered stalled.
    stall_threshold_minutes: int = 30
    # Seconds before an agent session with no heartbeat is considered dead.
    session_timeout_seconds: int = 60

    # --- Feature flags ---
    enable_monitoring_loop: bool = True
    enable_scheduler: bool = True


settings = Settings()
