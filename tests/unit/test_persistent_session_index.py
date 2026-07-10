from pathlib import Path

import pytest

from kohakuterrarium.studio.persistence.session_index import (
    SessionIndex,
    aggregate_stats,
    close_session_index,
    get_session_index_default,
    sidecar_path_for,
)
from kohakuterrarium.studio.persistence.session_index import (
    reconcile as reconcile_module,
)


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

    close_session_index()
    monkeypatch.delenv("KT_SESSION_DIR", raising=False)
    monkeypatch.setattr(persistence_store, "_SESSION_DIR", tmp_path)
    try:
        yield tmp_path
    finally:
        close_session_index()


@pytest.fixture
def index(session_dir):
    instance = SessionIndex(sidecar_path_for(session_dir))
    try:
        yield instance
    finally:
        instance.close()


def test_full_reconcile_lists_sidecar_with_pagination_and_sorting(
    session_dir, index, monkeypatch
):
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
    reconcile_module.reconcile(index, session_dir, full=True, workers=1)

    def explode(*_args, **_kwargs):
        raise AssertionError("SessionIndex.list must only read the sidecar")

    monkeypatch.setattr(reconcile_module, "read_entry_from_disk", explode)
    page = index.list(limit=1, offset=0).to_dict()

    assert page["total"] == 2
    assert page["offset"] == 0
    assert page["limit"] == 1
    assert [row["name"] for row in page["sessions"]] == ["newer"]
    assert sidecar_path_for(session_dir).exists()


def test_aggregate_stats_only_scans_sidecar(session_dir, index, monkeypatch):
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
    reconcile_module.reconcile(index, session_dir, full=True, workers=1)

    def explode(*_args, **_kwargs):
        raise AssertionError("aggregate_stats must not read session files")

    monkeypatch.setattr(reconcile_module, "read_entry_from_disk", explode)
    stats = aggregate_stats(index)

    assert stats["count"] == 2
    assert stats["by_status"] == {"paused": 1, "running": 1}
    assert stats["by_config_type"] == {"agent": 2}
    assert stats["agents_top"] == [["a", 1], ["b", 1]]


def test_incremental_reconcile_reads_only_new_session(session_dir, index, monkeypatch):
    _make_session(
        session_dir / "a.kohakutr",
        name="a",
        last_active="2024-01-01T00:00:00+00:00",
    )
    reconcile_module.reconcile(index, session_dir, full=True, workers=1)

    new_path = session_dir / "b.kohakutr"
    _make_session(
        new_path,
        name="b",
        last_active="2024-01-03T00:00:00+00:00",
    )

    calls: list[Path] = []
    real_read = reconcile_module.read_entry_from_disk

    def spy(path):
        calls.append(path)
        return real_read(path)

    monkeypatch.setattr(reconcile_module, "read_entry_from_disk", spy)
    report = reconcile_module.reconcile(index, session_dir, full=False, workers=1)
    page = index.list(limit=10, offset=0).to_dict()

    assert report.read == 1
    assert calls == [new_path]
    assert page["total"] == 2
    assert [row["name"] for row in page["sessions"]] == ["b", "a"]


def test_delete_session_files_removes_singleton_sidecar_row(session_dir):
    from kohakuterrarium.studio.persistence.store import delete_session_files

    _make_session(
        session_dir / "gone.kohakutr",
        name="gone",
        last_active="2024-01-01T00:00:00+00:00",
    )
    index = get_session_index_default(session_dir)
    assert index.list(limit=10, offset=0).total == 1

    deleted = delete_session_files("gone")
    page = index.list(limit=10, offset=0).to_dict()

    assert [path.name for path in deleted] == ["gone.kohakutr"]
    assert page["total"] == 0
    assert page["sessions"] == []


def test_full_reconcile_backfills_first_user_preview(session_dir, index):
    _make_session(
        session_dir / "task.kohakutr",
        name="task",
        last_active="2024-01-01T00:00:00+00:00",
        user_input="請幫我檢查 workspace 前端為什麼很卡",
        legacy_preview=True,
    )

    reconcile_module.reconcile(index, session_dir, full=True, workers=1)
    page = index.list(limit=10, offset=0).to_dict()

    assert page["total"] == 1
    assert page["sessions"][0]["preview"] == "請幫我檢查 workspace 前端為什麼很卡"


def test_unchanged_incremental_reconcile_preserves_preview_without_disk_read(
    session_dir, index, monkeypatch
):
    path = session_dir / "legacy.kohakutr"
    _make_session(
        path,
        name="legacy",
        last_active="2024-01-01T00:00:00+00:00",
        user_input="這是一個舊索引沒有保存的任務摘要",
        legacy_preview=True,
    )
    reconcile_module.reconcile(index, session_dir, full=True, workers=1)

    calls: list[Path] = []

    def spy(path):
        calls.append(path)
        raise AssertionError("unchanged sessions must not be read again")

    monkeypatch.setattr(reconcile_module, "read_entry_from_disk", spy)
    report = reconcile_module.reconcile(index, session_dir, full=False, workers=1)
    page = index.list(limit=1, offset=0).to_dict()

    assert report.read == 0
    assert calls == []
    assert page["sessions"][0]["preview"] == "這是一個舊索引沒有保存的任務摘要"


def test_default_index_bootstraps_once_and_paginates_without_legacy_scan(
    session_dir, monkeypatch
):
    from kohakuterrarium.studio.persistence import store as persistence_store

    _make_session(
        session_dir / "older.kohakutr",
        name="older",
        last_active="2024-01-01T00:00:00+00:00",
        user_input="older preview",
        legacy_preview=True,
    )
    _make_session(
        session_dir / "newer.kohakutr",
        name="newer",
        last_active="2024-01-02T00:00:00+00:00",
        user_input="newer preview",
        legacy_preview=True,
    )

    def explode(*_args, **_kwargs):
        raise AssertionError("bootstrap must not use the legacy session scan")

    monkeypatch.setattr(persistence_store, "all_session_files_default", explode)

    first = get_session_index_default(session_dir)
    first_page = first.list(limit=1, offset=0).to_dict()
    second_page = first.list(limit=1, offset=1).to_dict()
    second = get_session_index_default(session_dir)

    assert sidecar_path_for(session_dir).exists()
    assert second is first
    assert first_page["total"] == 2
    assert [row["name"] for row in first_page["sessions"]] == ["newer"]
    assert [row["name"] for row in second_page["sessions"]] == ["older"]
