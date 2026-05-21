from __future__ import annotations

from pathlib import Path

import pytest


def _make_session(path: Path, *, name: str, last_active: str, status: str = "paused") -> None:
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
