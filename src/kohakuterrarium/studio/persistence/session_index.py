"""Persistent materialized index for saved sessions.

The saved-session list/stats UI needs small summary rows, not the full
per-session event log.  The historical implementation rebuilt an in-memory
index by opening every ``*.kohakutr`` database and scanning event keys before
finally slicing a page.  This module keeps those summary rows in a small
central SQLite database next to the session files:

    ``<session_dir>/sessions_index.sqlite``

The index is an acceleration layer only.  Full resume/history paths still
resolve and open the real ``.kohakutr`` file so a stale index cannot make a
session unrecoverable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kohakuvault import KVault

from kohakuterrarium.studio.persistence.viewer.paths import (
    normalize_session_stem,
    pick_canonical_per_session,
)
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)

_INDEX_DB_NAME = "sessions_index.sqlite"
_INDEX_LOCK = threading.RLock()
_KV_KEYS_LIMIT = 2**31 - 1


def index_db_path(session_dir: Path) -> Path:
    return Path(session_dir) / _INDEX_DB_NAME


def _connect(session_dir: Path) -> sqlite3.Connection:
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_db_path(session_dir), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _connection(session_dir: Path):
    """Open an index DB connection and always close it.

    ``sqlite3.Connection`` is a transaction context manager only; using
    ``with sqlite3.connect(...)`` commits/rolls back but does *not* close
    the handle. That matters on Windows where open handles prevent
    deleting/moving session files and WAL sidecars.
    """
    conn = _connect(session_dir)
    try:
        yield conn
    finally:
        conn.close()


def init_index_db(session_dir: Path) -> None:
    """Create the persistent index schema if needed."""
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions_index (
            name TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,

            config_type TEXT,
            config_path TEXT,
            terrarium_name TEXT,
            agents_json TEXT NOT NULL DEFAULT '[]',
            status TEXT,
            created_at TEXT,
            last_active TEXT,
            preview TEXT,
            preview_scanned INTEGER NOT NULL DEFAULT 0,
            pwd TEXT,
            format_version INTEGER,

            parent_session_id TEXT,
            fork_point_json TEXT,
            forked_children_json TEXT NOT NULL DEFAULT '[]',
            migrated_from_version INTEGER,

            file_mtime REAL,
            wal_mtime REAL,
            shm_mtime REAL,
            file_size INTEGER,
            sort_ts REAL,
            indexed_at REAL NOT NULL,
            error TEXT
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions_index)")}
    if "preview_scanned" not in columns:
        conn.execute(
            "ALTER TABLE sessions_index "
            "ADD COLUMN preview_scanned INTEGER NOT NULL DEFAULT 0"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_index_sort "
        "ON sessions_index(sort_ts DESC, file_mtime DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_index_status "
        "ON sessions_index(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_index_config_type "
        "ON sessions_index(config_type)"
    )
    conn.commit()


def _json_dumps(value: Any, default: Any) -> str:
    if value is None:
        value = default
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        return json.dumps(default, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _to_ts(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _sidecar_mtime(path: Path, suffix: str) -> float | None:
    sidecar = Path(str(path) + suffix)
    try:
        return sidecar.stat().st_mtime
    except OSError:
        return None


def _meta_table(path: Path) -> KVault:
    meta = KVault(str(path), table="meta")
    meta.enable_auto_pack()
    return meta


def _load_meta_only(path: Path) -> dict[str, Any]:
    """Read only the ``meta`` table from a session DB.

    This intentionally avoids ``SessionStore`` because its constructor opens
    every table and restores event/channel counters by scanning keys.  The
    persistent list index only needs metadata fields.
    """
    meta = _meta_table(path)
    try:
        result: dict[str, Any] = {}
        for key_bytes in meta.keys(limit=_KV_KEYS_LIMIT):
            key = (
                key_bytes.decode("utf-8", errors="replace")
                if isinstance(key_bytes, bytes)
                else key_bytes
            )
            try:
                result[str(key)] = meta[key_bytes]
            except Exception as e:
                logger.debug(
                    "Failed to read session meta key for index",
                    path=str(path),
                    key=str(key),
                    error=str(e),
                    exc_info=True,
                )
        return result
    finally:
        close = getattr(meta, "close", None)
        if callable(close):
            close()


def _compact_preview_text(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _extract_text_preview(content: Any, limit: int = 200) -> str:
    """Flatten event content into the short session-list preview string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return _compact_preview_text(content, limit)
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                kind = str(part.get("type") or "")
                if kind == "text":
                    bits.append(str(part.get("text") or ""))
                elif kind in {"image", "image_url"}:
                    bits.append("[image]")
                elif kind == "file":
                    bits.append("[file]")
                elif "text" in part:
                    bits.append(str(part.get("text") or ""))
                else:
                    bits.append(f"[{kind or 'attachment'}]")
            elif part is not None:
                bits.append(str(part))
        return _compact_preview_text(" ".join(b for b in bits if b), limit)
    if isinstance(content, dict):
        kind = str(content.get("type") or "")
        if kind == "text" or "text" in content:
            return _compact_preview_text(content.get("text") or "", limit)
        if kind in {"image", "image_url"}:
            return "[image]"[:limit]
        if kind == "file":
            return "[file]"[:limit]
        if "content" in content:
            return _extract_text_preview(content.get("content"), limit)
        return _extract_text_preview([content], limit)
    return _compact_preview_text(content, limit)


def _events_table(path: Path) -> KVault:
    events = KVault(str(path), table="events")
    events.enable_auto_pack()
    return events


def _event_preview_sort_key(key: str, event: dict[str, Any]) -> tuple[int, float, str]:
    event_id = event.get("event_id")
    if isinstance(event_id, (int, float)):
        return (0, float(event_id), key)
    ts = event.get("ts")
    if isinstance(ts, (int, float)):
        return (1, float(ts), key)
    return (2, 0.0, key)


def _extract_first_user_preview(path: Path) -> str:
    """Read the first user_input preview from one session DB.

    This is only called in the short-lived subprocess backfill/lazy-fill path,
    never on the normal parent-process list/stats hot path.
    """
    events = _events_table(path)
    best: tuple[tuple[int, float, str], str] | None = None
    try:
        for key_bytes in events.keys(limit=_KV_KEYS_LIMIT):
            key = (
                key_bytes.decode("utf-8", errors="replace")
                if isinstance(key_bytes, bytes)
                else str(key_bytes)
            )
            try:
                event = events[key_bytes]
            except Exception as e:
                logger.debug(
                    "Failed to read session event for preview",
                    path=str(path),
                    key=key,
                    error=str(e),
                    exc_info=True,
                )
                continue
            if not isinstance(event, dict) or event.get("type") != "user_input":
                continue
            content = event.get("content")
            if content is None:
                content = event.get("text") or event.get("input")
            preview = _extract_text_preview(content)
            if not preview:
                continue
            sort_key = _event_preview_sort_key(key, event)
            if best is None or sort_key < best[0]:
                best = (sort_key, preview)
        return best[1] if best else ""
    finally:
        close = getattr(events, "close", None)
        if callable(close):
            close()


def _error_entry(path: Path, error: Exception | str) -> dict[str, Any]:
    path = Path(path)
    fallback_mtime = 0.0
    fallback_size = 0
    try:
        st = path.stat()
        fallback_mtime = st.st_mtime
        fallback_size = st.st_size
    except OSError:
        pass
    return {
        "name": normalize_session_stem(path),
        "filename": path.name,
        "path": str(path),
        "config_type": "unknown",
        "config_path": "",
        "terrarium_name": "",
        "agents": [],
        "status": "",
        "created_at": "",
        "last_active": "",
        "preview": "",
        "preview_scanned": 1,
        "pwd": "",
        "format_version": 1,
        "parent_session_id": None,
        "fork_point": None,
        "forked_children": [],
        "migrated_from_version": None,
        "file_mtime": fallback_mtime,
        "wal_mtime": _sidecar_mtime(path, "-wal"),
        "shm_mtime": _sidecar_mtime(path, "-shm"),
        "file_size": fallback_size,
        "sort_ts": fallback_mtime,
        "indexed_at": time.time(),
        "error": str(error),
    }


def _entry_from_meta(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Build one summary row from already-loaded session metadata."""
    path = Path(path)
    stat = path.stat()
    lineage = meta.get("lineage") or {}
    fork = lineage.get("fork") if isinstance(lineage, dict) else {}
    forked_children = meta.get("forked_children") or []
    agents = meta.get("agents") or []
    if not isinstance(agents, list):
        agents = [str(agents)] if agents else []
    last_active = meta.get("last_active", "")
    created_at = meta.get("created_at", "")
    preview = str(meta.get("preview") or meta.get("first_user_preview") or "")
    sort_ts = _to_ts(last_active) or _to_ts(created_at) or stat.st_mtime
    return {
        "name": normalize_session_stem(path),
        "filename": path.name,
        "path": str(path),
        "config_type": meta.get("config_type", "unknown"),
        "config_path": meta.get("config_path", ""),
        "terrarium_name": meta.get("terrarium_name", ""),
        "agents": agents,
        "status": meta.get("status", ""),
        "created_at": created_at,
        "last_active": last_active,
        # Backfill/refresh can fill this from events in the short-lived
        # subprocess. Runtime/live upserts use only meta and preserve any
        # existing indexed preview when this value is still empty.
        "preview": preview,
        "preview_scanned": 1 if preview else 0,
        "pwd": meta.get("pwd", ""),
        "format_version": meta.get("format_version", 1),
        "parent_session_id": (
            fork.get("parent_session_id") if isinstance(fork, dict) else None
        ),
        "fork_point": fork.get("fork_point") if isinstance(fork, dict) else None,
        "forked_children": [
            c.get("session_id") if isinstance(c, dict) else c for c in forked_children
        ],
        "migrated_from_version": (
            lineage.get("migration", {}).get("source_version")
            if isinstance(lineage, dict)
            else None
        ),
        "file_mtime": stat.st_mtime,
        "wal_mtime": _sidecar_mtime(path, "-wal"),
        "shm_mtime": _sidecar_mtime(path, "-shm"),
        "file_size": stat.st_size,
        "sort_ts": sort_ts,
        "indexed_at": time.time(),
        "error": None,
    }


def snapshot_store_meta(store: Any) -> dict[str, Any]:
    """Read metadata from an already-open ``SessionStore`` without event scans.

    ``SessionStore.load_meta()`` augments ``agents`` by scanning event keys,
    which is correct for resume/history but too expensive for lifecycle index
    updates. Runtime hooks already have a live store, so read only its meta
    KVault table and avoid opening/scanning the events table again.
    """
    result: dict[str, Any] = {}
    meta_table = getattr(store, "meta")
    for key_bytes in meta_table.keys(limit=_KV_KEYS_LIMIT):
        key = (
            key_bytes.decode("utf-8", errors="replace")
            if isinstance(key_bytes, bytes)
            else key_bytes
        )
        result[str(key)] = meta_table[key_bytes]
    return result


def _read_session_index_entry_local(
    path: Path,
    *,
    include_preview: bool = True,
) -> dict[str, Any]:
    """Read one session DB in the current process.

    This is intentionally private. Public refresh/backfill reads run in a
    short-lived subprocess on Windows so any SQLite/KVault handles opened for
    legacy ``.kohakutr`` files are released when that process exits.
    """
    path = Path(path)
    try:
        meta = _load_meta_only(path)
        entry = _entry_from_meta(path, meta)
        if include_preview and not entry.get("preview"):
            entry["preview"] = _extract_first_user_preview(path)
        entry["preview_scanned"] = 1 if include_preview else int(bool(entry.get("preview")))
        return entry
    except Exception as e:
        logger.debug(
            "Failed to build session index entry",
            path=str(path),
            error=str(e),
            exc_info=True,
        )
        return _error_entry(path, e)


def _read_entries_in_subprocess(
    paths: list[Path],
    *,
    include_preview: bool = True,
) -> list[dict[str, Any]]:
    if not paths:
        return []
    script = """
import json
import sys
from pathlib import Path
from kohakuterrarium.studio.persistence import session_index as si
payload = json.load(sys.stdin)
include_preview = bool(payload.get("include_preview", True))
paths = [Path(p) for p in payload.get("paths", [])]
entries = [si._read_session_index_entry_local(p, include_preview=include_preview) for p in paths]
json.dump(entries, sys.stdout, ensure_ascii=False, default=str)
""".strip()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    current_pythonpath = os.pathsep.join(str(p) for p in sys.path if p)
    if current_pythonpath:
        env["PYTHONPATH"] = (
            current_pythonpath
            if not existing_pythonpath
            else current_pythonpath + os.pathsep + existing_pythonpath
        )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(
            {
                "paths": [str(p) for p in paths],
                "include_preview": include_preview,
            },
            ensure_ascii=False,
        ),
        text=True,
        capture_output=True,
        env=env,
        timeout=max(30.0, min(300.0, len(paths) * 2.0)),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"subprocess exited {proc.returncode}")
    return json.loads(proc.stdout or "[]")


def read_session_index_entries(
    paths: list[Path],
    *,
    include_preview: bool = True,
) -> list[dict[str, Any]]:
    """Build summary rows for legacy/backfill paths.

    Normal list/stats requests do not call this after the index has rows. When
    a first-run backfill or explicit refresh is needed, perform the per-session
    DB reads in a child process so Windows file handles are not retained by the
    long-running API process.
    """
    paths = [Path(p) for p in paths]
    try:
        return _read_entries_in_subprocess(paths, include_preview=include_preview)
    except Exception as e:
        logger.warning(
            "Subprocess session-index backfill failed; returning error rows",
            error=str(e),
        )
        # Do not fall back to in-process reads here. On Windows, opening many
        # legacy .kohakutr SQLite files from the long-running API process can
        # keep file handles alive and break delete/resume flows. Surface rows
        # as errors instead; explicit session open/resume still uses the real
        # file resolver and remains the source of truth.
        return [_error_entry(path, e) for path in paths]


def read_session_index_entry(path: Path) -> dict[str, Any]:
    """Build one summary row from one session path."""
    entries = read_session_index_entries([Path(path)], include_preview=True)
    return entries[0] if entries else _error_entry(Path(path), "empty index read")


def _upsert_entry(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO sessions_index (
            name, filename, path,
            config_type, config_path, terrarium_name, agents_json,
            status, created_at, last_active, preview, preview_scanned,
            pwd, format_version,
            parent_session_id, fork_point_json, forked_children_json,
            migrated_from_version, file_mtime, wal_mtime, shm_mtime,
            file_size, sort_ts, indexed_at, error
        ) VALUES (
            :name, :filename, :path,
            :config_type, :config_path, :terrarium_name, :agents_json,
            :status, :created_at, :last_active, :preview, :preview_scanned,
            :pwd, :format_version,
            :parent_session_id, :fork_point_json, :forked_children_json,
            :migrated_from_version, :file_mtime, :wal_mtime, :shm_mtime,
            :file_size, :sort_ts, :indexed_at, :error
        )
        ON CONFLICT(name) DO UPDATE SET
            filename=excluded.filename,
            path=excluded.path,
            config_type=excluded.config_type,
            config_path=excluded.config_path,
            terrarium_name=excluded.terrarium_name,
            agents_json=excluded.agents_json,
            status=excluded.status,
            created_at=excluded.created_at,
            last_active=excluded.last_active,
            preview=COALESCE(NULLIF(excluded.preview, ''), sessions_index.preview, ''),
            preview_scanned=CASE
                WHEN excluded.preview_scanned THEN 1
                ELSE sessions_index.preview_scanned
            END,
            pwd=excluded.pwd,
            format_version=excluded.format_version,
            parent_session_id=excluded.parent_session_id,
            fork_point_json=excluded.fork_point_json,
            forked_children_json=excluded.forked_children_json,
            migrated_from_version=excluded.migrated_from_version,
            file_mtime=excluded.file_mtime,
            wal_mtime=excluded.wal_mtime,
            shm_mtime=excluded.shm_mtime,
            file_size=excluded.file_size,
            sort_ts=excluded.sort_ts,
            indexed_at=excluded.indexed_at,
            error=excluded.error
        """,
        {
            **entry,
            "agents_json": _json_dumps(entry.get("agents"), []),
            "fork_point_json": _json_dumps(entry.get("fork_point"), None),
            "forked_children_json": _json_dumps(entry.get("forked_children"), []),
            "preview_scanned": int(bool(entry.get("preview_scanned"))),
        },
    )


def upsert_session_path(path: Path, *, session_dir: Path | None = None) -> dict[str, Any]:
    """Read one session's metadata and upsert one index row."""
    path = Path(path)
    session_dir = Path(session_dir) if session_dir is not None else path.parent
    entry = read_session_index_entry(path)
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            _upsert_entry(conn, entry)
            conn.commit()
    return _public_entry(entry)


def upsert_session_meta(
    path: Path,
    meta: dict[str, Any],
    *,
    session_dir: Path | None = None,
) -> dict[str, Any]:
    """Upsert one index row from a live store's metadata snapshot.

    This path does not open the session database. Runtime lifecycle hooks use
    it while they already have an open ``SessionStore`` so the list index stays
    current without adding another SQLite handle to the session file.
    """
    path = Path(path)
    session_dir = Path(session_dir) if session_dir is not None else path.parent
    try:
        entry = _entry_from_meta(path, dict(meta))
    except Exception as e:
        entry = _error_entry(path, e)
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            _upsert_entry(conn, entry)
            conn.commit()
    return _public_entry(entry)


def delete_session_name(name: str, *, session_dir: Path) -> None:
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            conn.execute("DELETE FROM sessions_index WHERE name = ?", (name,))
            conn.commit()


def refresh_index(
    session_dir: Path,
    *,
    include_preview: bool = True,
) -> list[dict[str, Any]]:
    """Rebuild/repair the persistent index from canonical session files.

    This is used for first-run backfill and explicit Refresh.  Normal list and
    stats requests do not call it once rows exist.
    """
    session_dir = Path(session_dir)
    canonical = pick_canonical_per_session(session_dir)
    entries = read_session_index_entries(canonical, include_preview=include_preview)
    live_names = {entry["name"] for entry in entries}
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            for entry in entries:
                _upsert_entry(conn, entry)
            if live_names:
                placeholders = ",".join("?" for _ in live_names)
                conn.execute(
                    f"DELETE FROM sessions_index WHERE name NOT IN ({placeholders})",
                    tuple(live_names),
                )
            else:
                conn.execute("DELETE FROM sessions_index")
            conn.commit()
    return [
        _public_entry(entry)
        for entry in sorted(entries, key=_entry_sort_key, reverse=True)
    ]


def _row_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM sessions_index").fetchone()[0])


def ensure_index(session_dir: Path) -> None:
    """Ensure the index exists and backfill once if it has no rows."""
    session_dir = Path(session_dir)
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            count = _row_count(conn)
    if count == 0 and pick_canonical_per_session(session_dir):
        refresh_index(session_dir, include_preview=False)


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    public = {
        "name": entry.get("name", ""),
        "filename": entry.get("filename", ""),
        "config_type": entry.get("config_type", "unknown"),
        "config_path": entry.get("config_path", ""),
        "terrarium_name": entry.get("terrarium_name", ""),
        "agents": entry.get("agents") or [],
        "status": entry.get("status", ""),
        "created_at": entry.get("created_at", ""),
        "last_active": entry.get("last_active", ""),
        "preview": entry.get("preview", ""),
        "pwd": entry.get("pwd", ""),
        "format_version": entry.get("format_version", 1),
        "parent_session_id": entry.get("parent_session_id"),
        "fork_point": entry.get("fork_point"),
        "forked_children": entry.get("forked_children") or [],
        "migrated_from_version": entry.get("migrated_from_version"),
    }
    if entry.get("error"):
        public["error"] = True
        public["error_detail"] = entry.get("error")
    return public


def _row_to_public(row: sqlite3.Row) -> dict[str, Any]:
    entry = dict(row)
    entry["agents"] = _json_loads(entry.pop("agents_json", None), [])
    entry["fork_point"] = _json_loads(entry.pop("fork_point_json", None), None)
    entry["forked_children"] = _json_loads(entry.pop("forked_children_json", None), [])
    return _public_entry(entry)


def _entry_sort_key(entry: dict[str, Any]) -> tuple[float, float, str]:
    return (
        float(entry.get("sort_ts") or 0.0),
        float(entry.get("file_mtime") or 0.0),
        str(entry.get("name") or ""),
    )


def _fill_missing_page_previews(session_dir: Path, rows: list[sqlite3.Row]) -> bool:
    """Populate preview for current-page rows only.

    Existing indexes created before preview backfill have empty preview fields.
    Rebuilding every session would make the dashboard slow again, so normal
    list calls only repair rows that are actually visible on the current page.
    """
    missing_paths: list[Path] = []
    seen_names: set[str] = set()
    for row in rows:
        preview = str(row["preview"] or "")
        preview_scanned = int(row["preview_scanned"] or 0)
        if preview or preview_scanned:
            continue
        raw_path = str(row["path"] or "")
        if not raw_path:
            continue
        name = str(row["name"] or normalize_session_stem(Path(raw_path)))
        if name in seen_names:
            continue
        seen_names.add(name)
        missing_paths.append(Path(raw_path))
    if not missing_paths:
        return False

    rows_by_name = {
        str(row["name"] or normalize_session_stem(Path(str(row["path"] or "")))): row
        for row in rows
    }
    entries = read_session_index_entries(missing_paths, include_preview=True)
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            for entry in entries:
                name = str(entry.get("name") or "")
                row = rows_by_name.get(name)
                if row is None:
                    continue
                conn.execute(
                    """
                    UPDATE sessions_index
                    SET preview = COALESCE(NULLIF(?, ''), preview, ''),
                        preview_scanned = 1,
                        indexed_at = ?
                    WHERE name = ?
                    """,
                    (entry.get("preview", ""), time.time(), name),
                )
            conn.commit()
    return True


def query_sessions(
    session_dir: Path,
    *,
    limit: int = 20,
    offset: int = 0,
    search: str = "",
) -> dict[str, Any]:
    """Return a saved-session page from the persistent index."""
    ensure_index(session_dir)
    limit = max(0, min(int(limit), 500))
    offset = max(0, int(offset))
    q = (search or "").strip().lower()
    where = ""
    params: list[Any] = []
    if q:
        like = f"%{q}%"
        where = """
            WHERE lower(name) LIKE ?
               OR lower(filename) LIKE ?
               OR lower(config_type) LIKE ?
               OR lower(config_path) LIKE ?
               OR lower(terrarium_name) LIKE ?
               OR lower(preview) LIKE ?
               OR lower(pwd) LIKE ?
               OR lower(agents_json) LIKE ?
        """
        params.extend([like] * 8)

    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            total = int(
                conn.execute(f"SELECT COUNT(*) FROM sessions_index {where}", params).fetchone()[
                    0
                ]
            )
            rows = conn.execute(
                f"""
                SELECT * FROM sessions_index
                {where}
                ORDER BY sort_ts DESC, file_mtime DESC, name ASC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()

    if _fill_missing_page_previews(session_dir, rows):
        with _INDEX_LOCK:
            with _connection(session_dir) as conn:
                _init_schema(conn)
                total = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM sessions_index {where}",
                        params,
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    f"""
                    SELECT * FROM sessions_index
                    {where}
                    ORDER BY sort_ts DESC, file_mtime DESC, name ASC
                    LIMIT ? OFFSET ?
                    """,
                    [*params, limit, offset],
                ).fetchall()

    return {
        "sessions": [_row_to_public(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def query_stats(session_dir: Path) -> dict[str, Any]:
    ensure_index(session_dir)
    with _INDEX_LOCK:
        with _connection(session_dir) as conn:
            _init_schema(conn)
            rows = conn.execute("SELECT * FROM sessions_index").fetchall()

    sessions = [_row_to_public(row) for row in rows]
    if not sessions:
        return {
            "count": 0,
            "by_config_type": {},
            "by_status": {},
            "by_recency": {"1d": 0, "7d": 0, "30d": 0, "older": 0},
            "by_format_version": {},
            "agents_top": [],
            "average_age_seconds": None,
        }

    by_config_type: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_format: Counter[str] = Counter()
    agents: Counter[str] = Counter()
    by_recency = {"1d": 0, "7d": 0, "30d": 0, "older": 0}
    now = time.time()
    age_total = 0.0
    age_count = 0

    for entry in sessions:
        if entry.get("error"):
            continue
        by_config_type[entry.get("config_type", "unknown") or "unknown"] += 1
        by_status[entry.get("status", "unknown") or "unknown"] += 1
        by_format[str(entry.get("format_version", 1))] += 1
        for agent in entry.get("agents") or []:
            if agent:
                agents[str(agent)] += 1
        ts = _to_ts(entry.get("last_active") or entry.get("created_at"))
        if ts is not None:
            age = now - ts
            if age >= 0:
                age_total += age
                age_count += 1
                if age < 86400:
                    by_recency["1d"] += 1
                elif age < 86400 * 7:
                    by_recency["7d"] += 1
                elif age < 86400 * 30:
                    by_recency["30d"] += 1
                else:
                    by_recency["older"] += 1

    return {
        "count": len(sessions),
        "by_config_type": dict(by_config_type),
        "by_status": dict(by_status),
        "by_recency": by_recency,
        "by_format_version": dict(by_format),
        "agents_top": [list(pair) for pair in agents.most_common(5)],
        "average_age_seconds": (age_total / age_count) if age_count else None,
    }


def invalidate_index_files(session_dir: Path) -> None:
    """Test/maintenance helper: remove the persistent index DB and sidecars."""
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(index_db_path(session_dir)) + suffix).unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to remove session index sidecar", exc_info=True)
