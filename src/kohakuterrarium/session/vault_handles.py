"""Helpers for releasing KohakuVault-backed SQLite handles."""

from typing import Any


def close_and_release_vault(handle: Any) -> None:
    """Close a KohakuVault proxy and drop its native inner object.

    Some KohakuVault proxies do not expose ``close()`` and some keep the
    native SQLite owner reachable after ``close()``. On Windows that keeps the
    ``.kohakutr`` file locked until GC runs. Dropping the private native owner
    makes deletion deterministic after session shutdown.
    """
    if handle is None:
        return
    close = getattr(handle, "close", None)
    if callable(close):
        close()
    for attr in ("_inner", "_vault"):
        if hasattr(handle, attr):
            setattr(handle, attr, None)
