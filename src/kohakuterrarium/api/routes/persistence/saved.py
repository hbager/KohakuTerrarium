"""Persistence saved — list / delete saved sessions.

Routes drain from the legacy ``api/routes/sessions.py``; all logic
lives in ``studio/persistence/store.py``. Mounted under both
``/api/persistence/saved`` and ``/api/sessions`` (URL preservation
for the existing frontend ``sessionAPI`` callers).
"""

import asyncio

from fastapi import APIRouter, HTTPException

from kohakuterrarium.studio.persistence.store import (
    delete_session_files,
    disk_usage,
    list_sessions_page,
    session_stats,
)

router = APIRouter()


@router.get("/disk-usage")
async def get_disk_usage():
    """Aggregate disk usage of the saved-session directory.

    Pure filesystem — stats every canonical session file + its
    SQLite sidecars without opening any database. Off-loaded to a
    worker thread so the directory walk doesn't block the event loop
    on large session collections.
    """
    return await asyncio.to_thread(disk_usage)


@router.get("/stats")
async def get_session_stats():
    """Aggregations over the persistent saved-session index.

    Cheap after first-run lightweight backfill. Run in a thread because
    the very first call may initialize ``sessions_index.sqlite``.
    """
    return await asyncio.to_thread(session_stats)


@router.get("")
async def list_sessions(
    limit: int = 20,
    offset: int = 0,
    search: str = "",
    refresh: bool = False,
):
    """List saved sessions with search and pagination.

    Normal calls query ``sessions_index.sqlite`` directly, so ``limit``
    is now a real SQL page rather than a slice after opening every
    session DB. ``refresh=True`` explicitly repairs/backfills the index.
    """
    return await asyncio.to_thread(
        list_sessions_page,
        limit=limit,
        offset=offset,
        search=search,
        refresh=refresh,
    )


@router.delete("/{session_name}")
async def delete_session(session_name: str):
    """Delete a saved session file.

    Removes every on-disk file that belongs to the logical session
    (``foo.kohakutr.v2`` plus its ``foo.kohakutr`` v1 rollback when
    both exist). Falls back to fuzzy lookup if the user passes a
    legacy raw stem.
    """
    try:
        deleted_paths = await asyncio.to_thread(delete_session_files, session_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")

    if not deleted_paths:
        raise HTTPException(
            status_code=404, detail=f"Session not found: {session_name}"
        )
    return {
        "status": "deleted",
        "name": session_name,
        "files": [p.name for p in deleted_paths],
    }
