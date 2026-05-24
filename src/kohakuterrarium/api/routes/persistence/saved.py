"""Persistence saved — list / delete saved sessions.

Routes drain from the legacy ``api/routes/sessions.py``; all logic
lives in ``studio/persistence/store.py``. Mounted under both
``/api/persistence/saved`` and ``/api/sessions`` (URL preservation
for the existing frontend ``sessionAPI`` callers).
"""

from fastapi import APIRouter, HTTPException

from kohakuterrarium.api.routes.persistence._executor import (
    run_in_persistence_executor,
)
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
    SQLite sidecars without opening any database. Off-loaded to the
    dedicated persistence executor so the directory walk doesn't
    block the loop's default thread pool (which other ``to_thread``
    calls — chat WS, runtime graph, identity routes — share).
    """
    return await run_in_persistence_executor(disk_usage)


@router.get("/stats")
async def get_session_stats():
    """Aggregations over the persistent saved-session index.

    Cheap after first-run lightweight backfill. Runs on the dedicated
    persistence executor because the very first call may initialize
    ``sessions_index.sqlite``.
    """
    return await run_in_persistence_executor(session_stats)


def _filter_sessions(all_sessions, search: str):
    """Server-side search across session metadata fields.

    Pure CPU on Python dicts — moved out of the event loop into the
    persistence executor so a 1000-session search doesn't block other
    requests.  Same coerce-anything-to-str rules as before (multimodal
    preview blocks render as nested lists/dicts).
    """
    if not search:
        return all_sessions
    q = search.lower()

    def _as_str(v):
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return " ".join(_as_str(x) for x in v)
        if isinstance(v, dict):
            return " ".join(_as_str(x) for x in v.values())
        return str(v)

    return [
        s
        for s in all_sessions
        if q
        in " ".join(
            _as_str(s.get(k, ""))
            for k in (
                "name",
                "config_path",
                "config_type",
                "terrarium_name",
                "preview",
                "pwd",
                "agents",
            )
        ).lower()
    ]


@router.get("")
async def list_sessions(
    limit: int = 20,
    offset: int = 0,
    search: str = "",
    refresh: bool = False,
):
    """List saved sessions with search and pagination.

    Normal calls query ``sessions_index.sqlite`` directly on the
    dedicated persistence executor, so ``limit`` is now a real SQL page
    rather than a slice after opening every session DB. ``refresh=True``
    explicitly repairs/backfills the index.
    """
    return await run_in_persistence_executor(
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
        deleted_paths = await run_in_persistence_executor(
            delete_session_files, session_name
        )
    except HTTPException:
        raise
    except (PermissionError, OSError) as e:
        # The `.kohakutr` file is locked — typically a still-open
        # SQLite/WAL handle from a session that has not fully released
        # it. That is a transient conflict, not a server fault: 409.
        raise HTTPException(
            status_code=409,
            detail=f"Session file is in use and cannot be deleted yet: {e}",
        )
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
