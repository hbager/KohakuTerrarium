from __future__ import annotations

from pathlib import Path

import pytest


def _make_session(
    path: Path,
    *,
    name: str,
    last_active: str,
    status: str = "paused",
    user_input: str | None = None,
    legacy_preview: bool = False,
) -> None:
    from kohakuterrarium.session.store import SessionStore

    store = SessionStore(path)
    try:
        store.init_meta(
            session_id=name,
            config_type="agent",
            config_path=f"configs/{name}.yaml",
            pwd=str(path.parent),
            agents=[name],
        )
        store.meta["created_at"] = "2024-01-01T00:00:00+00:00"
        store.meta["last_active"] = last_active
        store.meta["status"] = status
        if user_input:
            store.append_event(name, "user_input", {"content": user_input})
            if legacy_preview:
                try:
                    del store.meta["preview"]
                except KeyError:
                    pass
            # Preserve the supplied timestamp order in list tests while still
            # exercising the preview capture path.
            store.meta["last_active"] = last_active
            store.meta["status"] = status
    finally:
        store.close(update_status=False)


@pytest.fixture
def session_dir(tmp_path, monkeypatch):
    from kohakuterrarium.studio.persistence import store as persistence_store

    monkeypatch.setattr(persistence_store, "_SESSION_DIR", tmp_path)
    return tmp_path


def test_persistent_index_queries_page_without_legacy_full_index(session_dir, monkeypatch):
    from kohakuterrarium.studio.persistence import store as persistence_store
    from kohakuterrarium.studio.persistence import session_index

    _make_session(
        session_dir / "older.kohakutr",
        name="older",
        last_active="2024-01-01T00:00:00+00:00",
    )
    _make_session(
        session_dir / "newer.kohakutr",
        name="newer",
        last_active="2024-01-02T00:00:00+00:00",
    )

    session_index.refresh_index(session_dir)

    def explode(*_args, **_kwargs):
        raise AssertionError("list_sessions_page must query sessions_index.sqlite, not rebuild the legacy in-memory index")

    monkeypatch.setattr(persistence_store, "build_session_index", explode)
    monkeypatch.setattr(persistence_store, "get_session_index", explode)
    monkeypatch.setattr(persistence_store, "_read_session_entry", explode)

    page = persistence_store.list_sessions_page(limit=1, offset=0)

    assert page["total"] == 2
    assert [row["name"] for row in page["sessions"]] == ["newer"]
    assert (session_dir / "sessions_index.sqlite").exists()


def test_persistent_index_stats_do_not_rebuild_legacy_index(session_dir, monkeypatch):
    from kohakuterrarium.studio.persistence import store as persistence_store
    from kohakuterrarium.studio.persistence import session_index

    _make_session(
        session_dir / "a.kohakutr",
        name="a",
        last_active="2024-01-02T00:00:00+00:00",
        status="paused",
    )
    _make_session(
        session_dir / "b.kohakutr",
        name="b",
        last_active="2024-01-03T00:00:00+00:00",
        status="running",
    )
    session_index.refresh_index(session_dir)

    def explode(*_args, **_kwargs):
        raise AssertionError("session_stats must aggregate sessions_index.sqlite, not rebuild legacy index")

    monkeypatch.setattr(persistence_store, "get_session_index", explode)
    monkeypatch.setattr(persistence_store, "build_session_index", explode)

    stats = persistence_store.session_stats()

    assert stats["count"] == 2
    assert stats["by_status"] == {"paused": 1, "running": 1}
    assert stats["by_config_type"] == {"agent": 2}
    assert stats["agents_top"] == [["a", 1], ["b", 1]]


def test_persistent_index_incrementally_upserts_single_session(session_dir, monkeypatch):
    from kohakuterrarium.studio.persistence import session_index

    _make_session(
        session_dir / "a.kohakutr",
        name="a",
        last_active="2024-01-01T00:00:00+00:00",
    )
    session_index.refresh_index(session_dir)

    _make_session(
        session_dir / "b.kohakutr",
        name="b",
        last_active="2024-01-03T00:00:00+00:00",
    )

    def explode(*_args, **_kwargs):
        raise AssertionError("upsert_session_path should only read the requested session")

    monkeypatch.setattr(session_index, "refresh_index", explode)

    session_index.upsert_session_path(session_dir / "b.kohakutr", session_dir=session_dir)
    page = session_index.query_sessions(session_dir, limit=10, offset=0)

    assert page["total"] == 2
    assert [row["name"] for row in page["sessions"]] == ["b", "a"]


def test_persistent_index_delete_removes_row(session_dir):
    from kohakuterrarium.studio.persistence import session_index
    from kohakuterrarium.studio.persistence.store import delete_session_files

    _make_session(
        session_dir / "gone.kohakutr",
        name="gone",
        last_active="2024-01-01T00:00:00+00:00",
    )
    session_index.refresh_index(session_dir)

    deleted = delete_session_files("gone")
    page = session_index.query_sessions(session_dir, limit=10, offset=0)

    assert [path.name for path in deleted] == ["gone.kohakutr"]
    assert page["total"] == 0
    assert page["sessions"] == []


def test_persistent_index_refresh_backfills_first_user_preview(session_dir):
    from kohakuterrarium.studio.persistence import session_index

    _make_session(
        session_dir / "task.kohakutr",
        name="task",
        last_active="2024-01-01T00:00:00+00:00",
        user_input="請幫我檢查 workspace 前端為什麼很卡",
        legacy_preview=True,
    )

    session_index.refresh_index(session_dir)
    page = session_index.query_sessions(session_dir, limit=10, offset=0)

    assert page["total"] == 1
    assert page["sessions"][0]["preview"] == "請幫我檢查 workspace 前端為什麼很卡"


def test_persistent_index_query_lazily_fills_legacy_empty_page_preview(
    session_dir, monkeypatch
):
    from kohakuterrarium.studio.persistence import session_index

    path = session_dir / "legacy.kohakutr"
    _make_session(
        path,
        name="legacy",
        last_active="2024-01-01T00:00:00+00:00",
        user_input="這是一個舊索引沒有保存的任務摘要",
        legacy_preview=True,
    )

    # Simulate the previous fast index implementation: row exists, preview is
    # empty, and it has never been event-scanned for preview.
    session_index.upsert_session_meta(
        path,
        {
            "session_id": "legacy",
            "config_type": "agent",
            "config_path": "configs/legacy.yaml",
            "pwd": str(session_dir),
            "agents": ["legacy"],
            "created_at": "2024-01-01T00:00:00+00:00",
            "last_active": "2024-01-01T00:00:00+00:00",
            "status": "paused",
            "preview": "",
        },
        session_dir=session_dir,
    )

    calls: list[tuple[list[Path], bool]] = []
    real_read = session_index.read_session_index_entries

    def spy(paths, *, include_preview=True):
        calls.append(([Path(p) for p in paths], include_preview))
        return real_read(paths, include_preview=include_preview)

    monkeypatch.setattr(session_index, "read_session_index_entries", spy)

    page = session_index.query_sessions(session_dir, limit=1, offset=0)

    assert calls == [([path], True)]
    assert page["sessions"][0]["preview"] == "這是一個舊索引沒有保存的任務摘要"


def test_first_list_backfills_metadata_only_then_lazily_fills_visible_preview(
    session_dir, monkeypatch
):
    from kohakuterrarium.studio.persistence import session_index

    older = session_dir / "older.kohakutr"
    newer = session_dir / "newer.kohakutr"
    _make_session(
        older,
        name="older",
        last_active="2024-01-01T00:00:00+00:00",
        user_input="older preview",
        legacy_preview=True,
    )
    _make_session(
        newer,
        name="newer",
        last_active="2024-01-02T00:00:00+00:00",
        user_input="newer preview",
        legacy_preview=True,
    )

    calls: list[tuple[list[Path], bool]] = []
    real_read = session_index.read_session_index_entries

    def spy(paths, *, include_preview=True):
        calls.append(([Path(p) for p in paths], include_preview))
        return real_read(paths, include_preview=include_preview)

    monkeypatch.setattr(session_index, "read_session_index_entries", spy)

    page = session_index.query_sessions(session_dir, limit=1, offset=0)

    assert len(calls) == 2
    assert set(calls[0][0]) == {older, newer}
    assert calls[0][1] is False
    assert calls[1] == ([newer], True)
    assert page["total"] == 2
    assert [row["name"] for row in page["sessions"]] == ["newer"]
    assert page["sessions"][0]["preview"] == "newer preview"
