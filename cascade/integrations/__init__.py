"""Cascade integration layer.

Bridges external systems (notably the Hermes agent) to the Cascade task
orchestration platform. The async REST client is always importable; the
monitor daemon is imported lazily so that consumers who only need the client
do not pay for its heavier runtime setup.

.. code-block:: python

    from cascade.integrations import CascadeClient

    async with CascadeClient("http://localhost:8100") as client:
        project = await client.create_project(name="Ship feature X")
"""

from __future__ import annotations

from cascade.integrations.hermes_bridge import (
    CascadeAPIError,
    CascadeClient,
    DotDict,
)

__all__ = ["CascadeClient", "CascadeAPIError", "DotDict", "MonitorDaemon"]


def __getattr__(name: str):
    """Lazy-load the monitor daemon to keep the client import lightweight."""
    if name == "MonitorDaemon":
        from cascade.integrations.monitor_daemon import MonitorDaemon

        return MonitorDaemon
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
